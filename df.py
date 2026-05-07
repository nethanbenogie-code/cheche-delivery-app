from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
import math
from datetime import datetime
import socket
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///delivery.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ------------------------- MODELS -------------------------
class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default='Zone')
    radius_km = db.Column(db.Float, nullable=False)
    base_df = db.Column(db.Float, nullable=False)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True)
    value = db.Column(db.String(255))

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

# ------------------------- HELPER FUNCTIONS -------------------------
def get_radius_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def get_local_ips():
    ips = []
    hostname = socket.gethostname()
    try:
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ips.append(ip)
    except:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except:
        pass
    return list(set(ips))

# ------------------------- LOGIN DECORATOR -------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ------------------------- ROUTES -------------------------
@app.route('/')
def index():
    sc = Setting.query.filter_by(key='shop_coords').first()
    sa = Setting.query.filter_by(key='shop_address').first()
    km_set = Setting.query.filter_by(key='price_per_km').first()
    rate = float(km_set.value) if km_set else 10.0
    zones = Location.query.order_by(Location.radius_km.asc()).all()
    
    manual_input = Setting.query.filter_by(key='manual_input_mode').first()
    hide_gps = Setting.query.filter_by(key='hide_gps_panel').first()
    
    return render_template('index.html',
                           saved_shop_coords=sc.value if sc else "",
                           saved_shop_addr=sa.value if sa else "",
                           rate=rate,
                           zones=[(z.radius_km, z.base_df) for z in zones],
                           manual_input_mode=manual_input.value == 'true' if manual_input else False,
                           hide_gps_panel=hide_gps.value == 'true' if hide_gps else False)

@app.route('/calculate', methods=['POST'])
def calculate():
    try:
        start_coords = request.form.get('start_coords')
        dest_coords = request.form.get('dest_coords')
        road_km = float(request.form.get('road_distance', 0))
        
        s_lat, s_lon = map(float, start_coords.split(','))
        d_lat, d_lon = map(float, dest_coords.split(','))
        
        km_set = Setting.query.filter_by(key='price_per_km').first()
        rate = float(km_set.value) if km_set else 10.0
        
        straight_dist = get_radius_dist(s_lat, s_lon, d_lat, d_lon)
        all_zones = Location.query.order_by(Location.radius_km.asc()).all()
        
        base = 0.0
        for zone in all_zones:
            if straight_dist <= zone.radius_km:
                base = zone.base_df
                break
                
        total = (road_km * rate) + base
        sc = Setting.query.filter_by(key='shop_coords').first()
        sa = Setting.query.filter_by(key='shop_address').first()
        
        return render_template('index.html', result={
            "success": True, "road_km": round(road_km, 2), "total": round(total, 2),
            "base": base, "rate": rate, "radius": round(straight_dist, 2),
        }, saved_shop_coords=sc.value if sc else "",
           saved_shop_addr=sa.value if sa else "",
           rate=rate, zones=[(z.radius_km, z.base_df) for z in all_zones])
    except Exception as e:
        return redirect(url_for('index'))

# ------------------------- ADMIN AUTHENTICATION -------------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash, password):
            session['admin_logged_in'] = True
            return redirect(url_for('admin'))
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/change-password', methods=['POST'])
@login_required
def change_password():
    new_password = request.form.get('new_password')
    if new_password:
        admin = Admin.query.first()
        if admin:
            admin.password_hash = generate_password_hash(new_password)
        else:
            db.session.add(Admin(username='admin', password_hash=generate_password_hash(new_password)))
        db.session.commit()
        flash('Password updated successfully')
    return redirect(url_for('admin'))

# ------------------------- ADMIN PANEL (PROTECTED) -------------------------
@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if request.method == 'POST':
        # Update KM Rate
        if 'update_km' in request.form:
            val = request.form.get('km_value')
            if val:
                s = Setting.query.filter_by(key='price_per_km').first()
                if s: s.value = val
                else: db.session.add(Setting(key='price_per_km', value=val))
                db.session.commit()

        # Update Shop Location
        elif 'update_shop' in request.form:
            c = request.form.get('shop_coords')
            a = request.form.get('shop_addr')
            if c and a:
                sc = Setting.query.filter_by(key='shop_coords').first()
                sa = Setting.query.filter_by(key='shop_address').first()
                if not sc:
                    db.session.add(Setting(key='shop_coords', value=c))
                    db.session.add(Setting(key='shop_address', value=a))
                else:
                    sc.value, sa.value = c, a
                db.session.commit()

        # Save/Update Zone
        elif 'save_area' in request.form:
            loc_id = request.form.get('id')
            name = request.form.get('name', 'Zone')
            rad = request.form.get('radius')
            fee = request.form.get('fee')
            if rad and fee:
                if loc_id:
                    loc = db.session.get(Location, loc_id)
                    if loc:
                        loc.name, loc.radius_km, loc.base_df = name, float(rad), float(fee)
                else:
                    db.session.add(Location(name=name, radius_km=float(rad), base_df=float(fee)))
                db.session.commit()
        
        # Interface Settings (manual input mode & hide GPS)
        elif 'update_interface' in request.form:
            manual_input = request.form.get('manual_input') == 'on'
            hide_gps = request.form.get('hide_gps') == 'on'
            
            s_manual = Setting.query.filter_by(key='manual_input_mode').first()
            if s_manual:
                s_manual.value = 'true' if manual_input else 'false'
            else:
                db.session.add(Setting(key='manual_input_mode', value='true' if manual_input else 'false'))
            
            s_gps = Setting.query.filter_by(key='hide_gps_panel').first()
            if s_gps:
                s_gps.value = 'true' if hide_gps else 'false'
            else:
                db.session.add(Setting(key='hide_gps_panel', value='true' if hide_gps else 'false'))
            
            db.session.commit()
        
        return redirect(url_for('admin'))

    km_price = Setting.query.filter_by(key='price_per_km').first()
    sc = Setting.query.filter_by(key='shop_coords').first()
    sa = Setting.query.filter_by(key='shop_address').first()
    now_str = datetime.now().strftime("%B %d, %Y — %I:%M %p")
    local_ips = get_local_ips()
    
    manual_input_setting = Setting.query.filter_by(key='manual_input_mode').first()
    hide_gps_setting = Setting.query.filter_by(key='hide_gps_panel').first()
    
    return render_template('admin.html',
                           locations=Location.query.order_by(Location.radius_km).all(),
                           km_price=km_price.value if km_price else "10.0",
                           shop_coords=sc.value if sc else "",
                           shop_addr=sa.value if sa else "",
                           now=now_str,
                           local_ips=local_ips,
                           manual_input_mode=manual_input_setting.value == 'true' if manual_input_setting else False,
                           hide_gps_setting=hide_gps_setting.value == 'true' if hide_gps_setting else False)

@app.route('/delete/<int:id>')
@login_required
def delete(id):
    loc = db.session.get(Location, id)
    if loc:
        db.session.delete(loc)
        db.session.commit()
    return redirect(url_for('admin'))

# ------------------------- INITIALIZE DATABASE -------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Setting.query.filter_by(key='price_per_km').first():
            db.session.add(Setting(key='price_per_km', value="10.0"))
            db.session.commit()
        if not Admin.query.first():
            default_hash = generate_password_hash('admin123')
            db.session.add(Admin(username='admin', password_hash=default_hash))
            db.session.commit()
    
    app.run(host='0.0.0.0', port=4500, debug=True)