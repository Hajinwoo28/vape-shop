import os
import uuid
import time
from datetime import datetime, timedelta
from jinja2 import DictLoader
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, extract, desc
from flask_migrate import Migrate
from werkzeug.utils import secure_filename

# --- 1. INITIALIZE APP & JINJA DICT TEMPLATES ---
app = Flask(__name__)
app.secret_key = "flex_vape_final_unified_key"

# --- SQLITE CONFIGURATION ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'flex_vape.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- JINJA DICTLOADER TEMPLATES MAP ---
TEMPLATES = {}

# --- 2. DATABASE MODELS ---
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    barcode = db.Column(db.String(50), unique=True, nullable=True)
    name = db.Column(db.String(100), nullable=False)
    flavor = db.Column(db.String(100))
    type = db.Column(db.String(50))
    version = db.Column(db.String(50))
    mg = db.Column(db.String(20))
    qty = db.Column(db.Integer, default=0)
    cost = db.Column(db.Float, default=0.0)
    price = db.Column(db.Float, default=0.0)
    image = db.Column(db.String(255), default='default.jpg')
    date_added = db.Column(db.DateTime, default=datetime.now)

class StockInLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.now)
    name = db.Column(db.String(100))
    flavor = db.Column(db.String(100))
    category = db.Column(db.String(50))
    qty = db.Column(db.Integer)

class StockOutLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.now)
    name = db.Column(db.String(100))
    flavor = db.Column(db.String(100))
    category = db.Column(db.String(50))
    qty = db.Column(db.Integer)
    price = db.Column(db.Float, default=0.0)
    cost = db.Column(db.Float, default=0.0)

# --- 3. LOGIN PROTECTION ---
# Set FLEX_USER and FLEX_PASS environment variables in production.
ADMIN_USER = os.environ.get("FLEX_USER", "flexinventory")
ADMIN_PASS = os.environ.get("FLEX_PASS", "flexsystem")

@app.before_request
def require_login():
    allowed_routes = ['login', 'static']
    if 'logged_in' not in session and request.endpoint not in allowed_routes:
        return redirect(url_for('login'))

# --- 4. HELPERS ---
def get_products_dict():
    products = Product.query.all()
    return {str(p.id): {
        "id": p.id,
        "barcode": p.barcode or '',
        "name": p.name,
        "flavor": p.flavor or '',
        "type": p.type or '',
        "version": p.version or '',
        "mg": p.mg or '',
        "qty": p.qty or 0,
        "cost": p.cost or 0.0,
        "price": p.price or 0.0,
        "image": p.image
    } for p in products}

# --- 5. ROUTES ---

@app.route('/')
def dashboard():
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    day_name = now.strftime('%A')
    month_name = now.strftime('%B')

    sales_today_count = StockOutLog.query.filter(func.date(StockOutLog.date) == today_str).count()
    rev_month = db.session.query(func.sum(StockOutLog.qty * StockOutLog.price)).filter(
        extract('month', StockOutLog.date) == now.month,
        extract('year', StockOutLog.date) == now.year
    ).scalar() or 0

    products_all = Product.query.all()
    total_qty = sum(p.qty for p in products_all)
    low_stock_count = Product.query.filter(Product.qty < 5).count()

    months_labels, sales_trend, purchase_trend = [], [], []
    for i in range(5, -1, -1):
        target_date = now - timedelta(days=i*30)
        months_labels.append(target_date.strftime("%b '%y"))
        s_val = db.session.query(func.sum(StockOutLog.qty)).filter(
            extract('month', StockOutLog.date) == target_date.month,
            extract('year', StockOutLog.date) == target_date.year
        ).scalar() or 0
        p_val = db.session.query(func.sum(StockInLog.qty)).filter(
            extract('month', StockInLog.date) == target_date.month,
            extract('year', StockInLog.date) == target_date.year
        ).scalar() or 0
        sales_trend.append(int(s_val))
        purchase_trend.append(int(p_val))

    top_selling = db.session.query(StockOutLog.name, func.sum(StockOutLog.qty).label('total')).group_by(StockOutLog.name).order_by(desc('total')).limit(5).all()

    total_sales_all = db.session.query(func.sum(StockOutLog.qty)).scalar() or 1
    cat_sales = db.session.query(StockOutLog.category, func.sum(StockOutLog.qty)).group_by(StockOutLog.category).all()
    category_progress = [{'name': c[0].capitalize() if c[0] else "Other", 'percentage': round((c[1]/total_sales_all)*100)} for c in cat_sales]

    stats = {
        'total_qty': total_qty, 
        'low_stock': low_stock_count,
        'revenue_month': f"₱{rev_month:,.2f}", 
        'sales_today_count': sales_today_count,
        'day_name': day_name,
        'month_name': month_name,
        'bar_labels': months_labels, 
        'bar_sales': sales_trend, 
        'bar_purchases': purchase_trend,
        'pie_labels': [item[0] for item in top_selling], 
        'pie_values': [int(item[1]) for item in top_selling],
        'stock_alerts': Product.query.filter(Product.qty < 10).order_by(Product.qty.asc()).limit(5).all(),
        'cat_progress': category_progress
    }
    return render_template('dashboard.html', stats=stats)

@app.route('/history')
def history():
    daily_history = db.session.query(
        func.date(StockOutLog.date).label('day'),
        func.count(StockOutLog.id).label('count'),
        func.sum(StockOutLog.qty * StockOutLog.price).label('revenue')
    ).group_by(func.date(StockOutLog.date)).order_by(desc('day')).limit(60).all()

    monthly_history = db.session.query(
        extract('year', StockOutLog.date).label('year'),
        extract('month', StockOutLog.date).label('month'),
        func.sum(StockOutLog.qty * StockOutLog.price).label('revenue')
    ).group_by('year', 'month').order_by(desc('year'), desc('month')).all()

    formatted_monthly = []
    for row in monthly_history:
        m_name = datetime(int(row.year), int(row.month), 1).strftime('%B')
        formatted_monthly.append({'year': row.year, 'month': m_name, 'revenue': row.revenue})

    return render_template('history.html', daily=daily_history, monthly=formatted_monthly)

@app.route('/inventory')
def inventory():
    return render_template('inventory.html', products=get_products_dict())

@app.route('/api/product/barcode/<barcode>')
def get_product_by_barcode(barcode):
    p = Product.query.filter_by(barcode=barcode).first()
    if p:
        return jsonify({"success": True, "id": p.id, "name": p.name, "flavor": p.flavor, "price": p.price, "qty": p.qty, "image": p.image})
    return jsonify({"success": False}), 404

@app.route('/products', methods=['GET', 'POST'])
def products():
    if request.method == 'POST':
        action = request.form.get('action')
        p_id = request.form.get('editing_key')
        
        if action == 'delete' and p_id:
            p = db.session.get(Product, p_id)
            if p: 
                db.session.delete(p)
                db.session.commit()
            return redirect(url_for('products'))

        name = request.form.get('name')
        price = float(request.form.get('price') or 0)
        cost = float(request.form.get('cost') or 0)
        barcode = request.form.get('barcode', '').strip() or str(int(time.time()))
        
        # Handle Image File Upload safely
        file = request.files.get('product_image')
        image_filename = None
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            image_filename = unique_filename

        if p_id:
            p = db.session.get(Product, p_id)
            if not p:
                return redirect(url_for('products'))
            p.name, p.price, p.barcode = name, price, barcode
            p.flavor = request.form.get('flavor')
            p.type = request.form.get('type')
            p.version = request.form.get('version')
            p.mg = request.form.get('mg')
            p.cost = cost
            if image_filename:
                p.image = image_filename
        else:
            qty = int(request.form.get('quantity') or 0)
            new_p = Product(name=name, price=price, barcode=barcode, 
                            qty=qty, 
                            type=request.form.get('type'), 
                            flavor=request.form.get('flavor'), 
                            cost=cost, 
                            version=request.form.get('version'), 
                            mg=request.form.get('mg'),
                            image=image_filename or 'default.jpg')
            db.session.add(new_p)
            
            if qty > 0:
                db.session.add(StockInLog(name=name, flavor=request.form.get('flavor'), category=request.form.get('type'), qty=qty))
                
        db.session.commit()
        return redirect(url_for('products'))
    return render_template('products.html', products=get_products_dict())

@app.route('/sales', methods=['GET', 'POST'])
def sales():
    if request.method == 'POST':
        p_id = request.form.get('product_key')
        qty = int(request.form.get('quantity') or 0)
        p = db.session.get(Product, p_id)
        if p and qty > 0 and p.qty >= qty:
            p.qty -= qty
            db.session.add(StockOutLog(name=p.name, flavor=p.flavor, category=p.type, qty=qty, price=p.price, cost=p.cost))
            db.session.commit()
            flash("Sale recorded successfully.", "success")
        else:
            flash("Insufficient inventory level.", "danger")
        return redirect(url_for('sales'))
    logs = StockOutLog.query.order_by(StockOutLog.id.desc()).limit(50).all()
    return render_template('sales.html', products=get_products_dict(), logs=logs)

@app.route('/reports')
def reports():
    period = request.args.get('period', 'daily')
    today = datetime.now().date()
    start_date = today - timedelta(days=7) if period == 'weekly' else today
    start_date_str = start_date.strftime('%Y-%m-%d')
    
    logs_out = StockOutLog.query.filter(func.date(StockOutLog.date) >= start_date_str).all()
    logs_in = StockInLog.query.filter(func.date(StockInLog.date) >= start_date_str).all()
    
    movement = []
    for p in Product.query.all():
        sold = sum(l.qty for l in logs_out if l.name == p.name and l.flavor == p.flavor)
        added = sum(l.qty for l in logs_in if l.name == p.name and l.flavor == p.flavor)
        opening = p.qty + sold - added
        if opening > 0 or added > 0 or sold > 0:
            movement.append({'name': f"{p.name} {p.flavor}", 'open': opening, 'new': added, 'sold': sold, 'end': p.qty})

    # Critical Low Stock Warning mapping
    low_stocks = {}
    low_stock_items = Product.query.filter(Product.qty < 5).all()
    if low_stock_items:
        low_stocks["low"] = low_stock_items

    return render_template('reports.html', movement=movement, revenue=sum(l.qty*l.price for l in logs_out), sales_count=len(logs_out), date=today.strftime("%B %d, %Y"), now=datetime.now().strftime("%H:%M"), period=period, report_label="Inventory Audit Report", low_stocks=low_stocks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid authentication credentials.", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- 6. DEFINE EMBEDDED JINJA TEMPLATE STRINGS ---

TEMPLATES["base.html"] = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>F.L.E.X | Inventory Management</title>
    
    <!-- Professional Font & Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    
    <!-- Barcode Scanner Library -->
    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>

    <style>
        :root {
            --navy: #162135;
            --purple: #705194;
            --bg-body: #f8fafc;
            --sidebar-width: 260px;
            --text-main: #1e293b;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --header-height: 60px;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body { 
            font-family: 'Inter', sans-serif; 
            background: var(--bg-body); 
            color: var(--text-main);
            display: flex; 
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* --- SCANNER OVERLAY STYLES --- */
        #fsScannerContainer {
            display: none;
            position: fixed;
            inset: 0;
            background: #000;
            z-index: 9999;
        }

        #fsReader { width: 100%; height: 100%; }
        #fsReader video { object-fit: cover !important; }

        .scan-overlay {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            pointer-events: none;
        }

        .scan-frame {
            position: relative;
            width: 280px;
            height: 280px;
            border: 1px solid rgba(255,255,255,0.2);
        }

        /* White Corners */
        .corner {
            position: absolute;
            width: 40px;
            height: 40px;
            border: 5px solid #fff;
            border-radius: 12px;
        }
        .top-left { top: -5px; left: -5px; border-right: 0; border-bottom: 0; border-radius: 12px 0 0 0; }
        .top-right { top: -5px; right: -5px; border-left: 0; border-bottom: 0; border-radius: 0 12px 0 0; }
        .bottom-left { bottom: -5px; left: -5px; border-right: 0; border-top: 0; border-radius: 0 0 0 12px; }
        .bottom-right { bottom: -5px; right: -5px; border-left: 0; border-top: 0; border-radius: 0 0 12px 0; }

        /* Animated Blue Line */
        .scan-line {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 3px;
            background: #3b82f6;
            box-shadow: 0 0 15px #3b82f6;
            animation: scanMove 2s infinite linear;
        }

        @keyframes scanMove {
            0% { top: 0; }
            50% { top: 100%; }
            100% { top: 0; }
        }

        .scan-text {
            color: white;
            margin-top: 40px;
            font-weight: 600;
            text-shadow: 0 2px 4px rgba(0,0,0,0.5);
            letter-spacing: 1px;
        }

        .scan-close-btn {
            position: absolute;
            top: 40px;
            left: 25px;
            background: rgba(0,0,0,0.5);
            color: white;
            border: none;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            font-size: 20px;
            cursor: pointer;
            pointer-events: auto;
        }

        /* --- MOBILE TOP BAR --- */
        .mobile-header {
            display: none; 
            position: fixed;
            top: 0; left: 0; right: 0;
            height: var(--header-height);
            background: var(--navy);
            color: white;
            align-items: center;
            justify-content: space-between; 
            padding: 0 15px;
            z-index: 1001;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        .menu-btn {
            background: rgba(255,255,255,0.1);
            border: none;
            color: white;
            font-size: 1.2rem;
            cursor: pointer;
            width: 40px;
            height: 40px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: 0.3s;
        }

        /* --- SIDEBAR --- */
        .sidebar { 
            width: var(--sidebar-width); 
            background: var(--navy); 
            height: 100vh; 
            position: fixed; 
            left: 0; top: 0; 
            z-index: 1002; 
            color: white; 
            display: flex;
            flex-direction: column;
            padding: 30px 0 20px 0;
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .sidebar-header { padding: 0 25px 20px 25px; text-align: center; }
        .logo-img { width: 90px; height: 90px; border-radius: 50%; border: 4px solid var(--purple); background: #1D2D44; margin-bottom: 15px; object-fit: cover; }
        .sidebar-header h3 { font-weight: 800; letter-spacing: 2px; font-size: 1.3rem; color: white; }
        .divider { height: 1px; background: rgba(255,255,255,0.08); margin: 15px 25px; }
        .menu-label { padding: 10px 25px; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px; color: #576c8c; font-weight: 700; }
        .nav-links { list-style: none; flex-grow: 1; padding: 0 15px; }
        .nav-links li { margin-bottom: 8px; }
        .nav-links a { color: #94a3b8; text-decoration: none; padding: 12px 20px; display: flex; align-items: center; gap: 15px; font-size: 0.95rem; font-weight: 500; transition: 0.2s; border-radius: 12px; }
        .nav-links a:hover { color: white; background: rgba(255,255,255,0.05); }
        .nav-links a.active { background: var(--purple); color: white !important; font-weight: 600; box-shadow: 0 10px 20px -10px var(--purple); }
        .nav-links a i { font-size: 1.2rem; width: 25px; opacity: 0.8; }

        /* --- LOGOUT AREA --- */
        .logout-container { padding: 0 15px; margin-top: auto; }
        .logout-link { padding: 15px 20px; color: #ff8a8a; text-decoration: none; font-size: 0.95rem; font-weight: 600; background: rgba(255,255,255,0.04); border-radius: 14px; display: flex; align-items: center; gap: 12px; transition: 0.3s; }
        .logout-link:hover { background: rgba(255,138,138,0.1); color: #ff6b6b; }

        /* --- OVERLAY & CONTENT --- */
        .sidebar-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1000; backdrop-filter: blur(2px); }
        .main-content { margin-left: var(--sidebar-width); padding: 40px; width: calc(100% - var(--sidebar-width)); flex-grow: 1; }
        .main-content.no-sidebar { margin-left: 0; width: 100%; }

        /* --- FLASH MESSAGES --- */
        .flash-container { margin-bottom: 20px; display: flex; flex-direction: column; gap: 10px; }
        .flash-msg { display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-radius: 12px; font-size: 0.875rem; font-weight: 600; position: relative; }
        .flash-success { background: #d1fae5; color: #065f46; border: 1px solid #a7f3d0; }
        .flash-danger  { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
        .flash-warning { background: #fef9c3; color: #854d0e; border: 1px solid #fde68a; }
        .flash-close { background: none; border: none; cursor: pointer; font-size: 1.1rem; margin-left: auto; opacity: 0.6; line-height: 1; padding: 0 4px; }
        .flash-close:hover { opacity: 1; }

        @media (max-width: 1024px) {
            .mobile-header { display: flex; }
            .sidebar { transform: translateX(-100%); }
            .sidebar.open { transform: translateX(0); }
            .sidebar-overlay.show { display: block; }
            .main-content { margin-left: 0; width: 100%; padding: 20px; padding-top: 80px; }
        }
    </style>
</head>
<body>

    <!-- GLOBAL FULL SCREEN SCANNER UI -->
    <div id="fsScannerContainer">
        <div id="fsReader"></div>
        <div class="scan-overlay">
            <div class="scan-frame">
                <div class="corner top-left"></div>
                <div class="corner top-right"></div>
                <div class="corner bottom-left"></div>
                <div class="corner bottom-right"></div>
                <div class="scan-line"></div>
            </div>
            <p class="scan-text">ALIGN BARCODE WITHIN FRAME</p>
        </div>
        <button class="scan-close-btn" onclick="stopFSScanner()">
            <i class="fas fa-times"></i>
        </button>
    </div>

    {% if session.get('logged_in') %}
    <header class="mobile-header">
        <button class="menu-btn" id="openMenu">
            <i class="fa-solid fa-bars"></i>
        </button>
        <span style="font-weight: 800; letter-spacing: 1px; font-size: 1.1rem; position: absolute; left: 50%; transform: translateX(-50%);">F.L.E.X</span>
        <div style="width: 40px;"></div>
    </header>

    <div class="sidebar-overlay" id="overlay"></div>

    <nav class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <div style="width: 90px; height: 90px; border-radius: 50%; border: 4px solid var(--purple); background: #1D2D44; margin: 0 auto 15px auto; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 2rem; color: #fff;">F</div>
            <h3>F.L.E.X</h3>
        </div>

        <div class="divider"></div>
        <div class="menu-label">Main Menu</div>

        <ul class="nav-links">
            <li><a href="/" class="{{ 'active' if request.path == '/' }}"><i class="fa-solid fa-chart-pie"></i> <span>Dashboard</span></a></li>
            <li><a href="/inventory" class="{{ 'active' if request.path == '/inventory' }}"><i class="fa-solid fa-boxes-stacked"></i> <span>Inventory</span></a></li>
            <li><a href="/sales" class="{{ 'active' if request.path == '/sales' }}"><i class="fa-solid fa-cart-shopping"></i> <span>Sales</span></a></li>
            <li><a href="/products" class="{{ 'active' if request.path == '/products' }}"><i class="fa-solid fa-tags"></i> <span>Products</span></a></li>
            <li><a href="/reports" class="{{ 'active' if request.path == '/reports' }}"><i class="fa-solid fa-file-waveform"></i> <span>Reports</span></a></li>
        </ul>

        <div class="logout-container">
            <a href="/logout" class="logout-link">
                <i class="fa-solid fa-power-off"></i> <span>Logout System</span>
            </a>
        </div>
    </nav>
    {% endif %}

    <main class="main-content {{ 'no-sidebar' if not session.get('logged_in') }}">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        <div class="flash-container">
            {% for category, message in messages %}
            <div class="flash-msg flash-{{ category }}">
                <i class="fas {{ 'fa-check-circle' if category == 'success' else 'fa-circle-exclamation' }}"></i>
                {{ message }}
                <button class="flash-close" onclick="this.parentElement.remove()">&times;</button>
            </div>
            {% endfor %}
        </div>
        {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>

    <script>
        // --- SIDEBAR LOGIC ---
        const openBtn = document.getElementById('openMenu');
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('overlay');

        if (openBtn) {
            openBtn.addEventListener('click', () => {
                sidebar.classList.add('open');
                overlay.classList.add('show');
            });
        }

        if (overlay) {
            overlay.addEventListener('click', () => {
                sidebar.classList.remove('open');
                overlay.classList.remove('show');
            });
        }
        
        window.addEventListener('resize', () => {
            if (window.innerWidth > 1024 && sidebar) {
                sidebar.classList.remove('open');
                overlay.classList.remove('show');
            }
        });

        // --- GLOBAL SCANNER LOGIC ---
        let fsHtml5QrCode;

        async function startFSScanner(onSuccessCallback) {
            const container = document.getElementById('fsScannerContainer');
            container.style.display = 'block';

            fsHtml5QrCode = new Html5Qrcode("fsReader");
            
            const config = { 
                fps: 20, 
                qrbox: { width: 280, height: 280 },
                aspectRatio: 1.0 
            };

            try {
                await fsHtml5QrCode.start(
                    { facingMode: "environment" }, 
                    config, 
                    (decodedText) => {
                        // Success Feedback
                        playScanSound();
                        onSuccessCallback(decodedText);
                        stopFSScanner();
                    }
                );
            } catch (err) {
                console.error(err);
                alert("Camera access error. Ensure you are using HTTPS.");
                stopFSScanner();
            }
        }

        function stopFSScanner() {
            if (fsHtml5QrCode) {
                fsHtml5QrCode.stop().then(() => {
                    document.getElementById('fsScannerContainer').style.display = 'none';
                }).catch(() => {
                    document.getElementById('fsScannerContainer').style.display = 'none';
                });
            } else {
                document.getElementById('fsScannerContainer').style.display = 'none';
            }
        }

        function playScanSound() {
            try {
                const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = audioCtx.createOscillator();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(880, audioCtx.currentTime);
                osc.connect(audioCtx.destination);
                osc.start();
                osc.stop(audioCtx.currentTime + 0.1);
            } catch(e) {}
        }
    </script>
</body>
</html>
"""

TEMPLATES["dashboard.html"] = """
{% extends "base.html" %}

{% block content %}
<!-- Include Chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<style>
    :root {
        --text-dark: #1a2b4b;
        --text-gray: #8492a6;
        --blue-main: #4e73df;
        --border-color: #edf2f7;
        --purple-brand: #705194;
    }

    .dashboard-wrapper {
        width: 100%;
        max-width: 100%;
        overflow-x: hidden;
    }

    /* --- TOP HEADER SECTION --- */
    .dashboard-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 25px;
        flex-wrap: wrap;
        gap: 15px;
    }

    .dashboard-header h1 {
        margin: 0;
        font-weight: 800;
        color: var(--text-dark);
        font-size: 1.8rem;
    }

    .history-btn {
        background: var(--purple-brand);
        color: white;
        padding: 10px 20px;
        border-radius: 10px;
        text-decoration: none;
        font-size: 0.85rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        gap: 8px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 12px rgba(112, 81, 148, 0.2);
    }

    .history-btn:hover {
        background: var(--text-dark);
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(26, 43, 75, 0.3);
        color: white;
    }

    /* --- 1. TOP METRIC CARDS --- */
    .metrics-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 15px;
        margin-bottom: 20px;
    }

    .m-card {
        background: white;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid var(--border-color);
        box-shadow: 0 2px 10px rgba(0,0,0,0.02);
    }

    .m-card span { display: block; color: var(--text-gray); font-weight: 700; font-size: 0.75rem; text-transform: uppercase; margin-bottom: 10px; letter-spacing: 0.5px; }
    .m-card h2 { margin: 0; font-size: 1.6rem; color: var(--blue-main); font-weight: 800; }

    /* --- 2. MIDDLE CHARTS SECTION --- */
    .charts-grid {
        display: grid;
        grid-template-columns: 1.8fr 1.2fr;
        gap: 20px;
        margin-bottom: 20px;
        align-items: start;
    }

    .chart-container {
        background: white;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid var(--border-color);
        min-height: 350px;
        position: relative;
    }

    .chart-header { font-weight: 800; color: var(--text-dark); margin-bottom: 15px; display: block; }

    /* --- 3. BOTTOM SECTION --- */
    .details-grid {
        display: grid;
        grid-template-columns: 1.8fr 1.2fr;
        gap: 20px;
    }

    .table-card, .category-card {
        background: white;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid var(--border-color);
    }

    .table-wrap { width: 100%; overflow-x: auto; }
    .alert-table { width: 100%; border-collapse: collapse; min-width: 400px; }
    .alert-table th { text-align: left; color: var(--text-gray); font-size: 0.75rem; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9; }
    .alert-table td { padding: 12px 0; border-bottom: 1px solid #f7fafc; font-size: 0.85rem; }

    .badge-cat { background: #e0e7ff; color: #4338ca; padding: 3px 8px; border-radius: 5px; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; }

    /* Category Bars */
    .cat-item { margin-bottom: 15px; }
    .cat-info { display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 0.8rem; font-weight: 700; }
    .progress-bg { height: 8px; background: #edf2f7; border-radius: 10px; }
    .progress-fill { height: 100%; border-radius: 10px; transition: width 1s ease-in-out; }

    @media (max-width: 1024px) {
        .charts-grid, .details-grid { grid-template-columns: 1fr; }
        .chart-container { min-height: 300px; }
    }
</style>

<div class="dashboard-wrapper">
    
    <!-- DASHBOARD HEADER -->
    <div class="dashboard-header">
        <h1>Dashboard</h1>
        <a href="/history" class="history-btn">
            <i class="fa-solid fa-clock-rotate-left"></i> View Business History
        </a>
    </div>

    <!-- TOP CARDS -->
    <div class="metrics-grid">
        <div class="m-card">
            <span>Current Stock</span>
            <h2>{{ stats.total_qty }}</h2>
        </div>
        
        <div class="m-card">
            <!-- Dynamic Day: Resets at Midnight -->
            <span>Sales Today ({{ stats.day_name }})</span>
            <h2>{{ stats.sales_today_count }}</h2>
        </div>
        
        <div class="m-card">
            <!-- Dynamic Month: Resets on the 1st -->
            <span>Revenue for {{ stats.month_name }}</span>
            <h2 style="color: var(--purple-brand);">{{ stats.revenue_month }}</h2>
        </div>
        
        <div class="m-card">
            <span>Low Stock Items</span>
            <h2 style="color: #ef4444;">{{ stats.low_stock }}</h2>
        </div>
    </div>

    <!-- CHARTS -->
    <div class="charts-grid">
        <div class="chart-container">
            <span class="chart-header">Sales and Purchases Trend</span>
            <div style="height: 280px;">
                <canvas id="barChart"></canvas>
            </div>
        </div>
        <div class="chart-container">
            <span class="chart-header">Top Selling Products</span>
            <div style="height: 280px;">
                <canvas id="pieChart"></canvas>
            </div>
        </div>
    </div>

    <!-- BOTTOM SECTION -->
    <div class="details-grid">
        
        <!-- DYNAMIC STOCK ALERTS -->
        <div class="table-card">
            <span class="chart-header">Stock Alert</span>
            <div class="table-wrap">
                <table class="alert-table">
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Category</th>
                            <th>Quantity</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for prod in stats.stock_alerts %}
                        <tr>
                            <td><strong>{{ prod.name }}</strong> <small>{{ prod.flavor }}</small></td>
                            <td><span class="badge-cat">{{ prod.type }}</span></td>
                            <td style="color: #ef4444; font-weight:bold;">{{ prod.qty }} left</td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="3" style="text-align: center; color: var(--text-gray);">All items are well stocked.</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- DYNAMIC SALES BY CATEGORY -->
        <div class="category-card">
            <span class="chart-header">Sales by Categories</span>
            {% for cat in stats.cat_progress %}
            <div class="cat-item">
                <div class="cat-info">
                    <span>{{ cat.name }}</span>
                    <small>{{ cat.percentage }}%</small>
                </div>
                <div class="progress-bg">
                    <div class="progress-fill" 
                         style="width: {{ cat.percentage }}%; background: var(--blue-main);">
                    </div>
                </div>
            </div>
            {% else %}
            <p style="font-size: 0.8rem; color: var(--text-gray);">No category data available yet.</p>
            {% endfor %}
        </div>
    </div>
</div>

<script>
    const chartOptions = {
        maintainAspectRatio: false,
        responsive: true,
        plugins: {
            legend: { 
                position: 'bottom', 
                labels: { boxWidth: 12, font: { size: 11, weight: '600' } } 
            }
        },
        scales: {
            y: { beginAtZero: true, grid: { display: false } },
            x: { grid: { display: false } }
        }
    };

    // Bar Chart
    new Chart(document.getElementById('barChart'), {
        type: 'bar',
        data: {
            labels: {{ stats.bar_labels | tojson }},
            datasets: [{
                label: 'Sales (Units)',
                data: {{ stats.bar_sales | tojson }},
                backgroundColor: '#4e73df',
                borderRadius: 4
            }, {
                label: 'Restocks (Units)',
                data: {{ stats.bar_purchases | tojson }},
                backgroundColor: '#1cc88a',
                borderRadius: 4
            }]
        },
        options: chartOptions
    });

    // Pie Chart
    new Chart(document.getElementById('pieChart'), {
        type: 'doughnut',
        data: {
            labels: {{ stats.pie_labels | tojson }},
            datasets: [{
                data: {{ stats.pie_values | tojson }},
                backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b'],
                borderWidth: 0
            }]
        },
        options: {
            maintainAspectRatio: false,
            responsive: true,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 10, padding: 15 } }
            },
            cutout: '70%'
        }
    });
</script>
{% endblock %}
"""

TEMPLATES["inventory.html"] = """
{% extends "base.html" %}

{% block content %}
<style>
    :root {
        --purple-grad: linear-gradient(135deg, #705194 0%, #553c7b 100%);
    }

    .inventory-container {
        max-width: 100%;
        margin: 0 auto;
        padding: 10px;
    }

    /* --- TOP HEADER --- */
    .header-flex {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 25px;
    }

    .header-title h1 { font-size: 1.8rem; font-weight: 800; color: #1a2b4b; margin: 0; }
    .header-title p { color: #8492a6; margin: 3px 0 0 0; font-size: 0.9rem; }

    .notif-bell {
        background: white; width: 45px; height: 45px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05); color: #1a2b4b; position: relative;
    }

    /* --- LIST CARD --- */
    .list-card {
        background: white; border-radius: 20px; padding: 25px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.03); border: 1px solid #edf2f7;
    }

    .list-header {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 25px; flex-wrap: wrap; gap: 15px;
    }

    .search-box { position: relative; width: 100%; max-width: 350px; }
    .search-box i { position: absolute; left: 15px; top: 50%; transform: translateY(-50%); color: #cbd5e1; }
    .search-box input {
        width: 100%; padding: 12px 15px 12px 45px;
        border: 1px solid #e2e8f0; border-radius: 50px; font-size: 0.85rem;
        transition: 0.3s;
    }
    .search-box input:focus { border-color: #705194; outline: none; box-shadow: 0 0 0 3px rgba(112, 81, 148, 0.1); }

    /* --- TABLE STYLING --- */
    .table-responsive { width: 100%; overflow-x: auto; border-radius: 12px; }
    .product-table { width: 100%; border-collapse: collapse; min-width: 1000px; }
    .product-table th { 
        text-align: left; padding: 15px; font-size: 0.65rem; text-transform: uppercase; 
        color: #718096; background: #f8fafc; border-bottom: 1px solid #edf2f7; 
    }
    .product-table td { padding: 15px; border-bottom: 1px solid #f7fafc; vertical-align: middle; }

    .img-cell { width: 48px; height: 48px; border-radius: 10px; background: #f1f5f9; overflow: hidden; }
    .img-cell img { width: 100%; height: 100%; object-fit: cover; }

    .name-cell strong { display: block; color: #1a2b4b; font-size: 0.9rem; }
    .flavor-cell { color: #705194; font-weight: 600; font-size: 0.85rem; }

    .badge-cat { background: #e0e7ff; color: #4338ca; padding: 5px 12px; border-radius: 50px; font-size: 0.65rem; font-weight: 800; text-transform: uppercase; }

    /* Stock Status */
    .stock-pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 6px 14px; border-radius: 50px; font-weight: 800; font-size: 0.75rem;
    }
    .stock-ok { background: #d1fae5; color: #065f46; }
    .stock-low { background: #fee2e2; color: #991b1b; }
    .stock-out { background: #f3f4f6; color: #4b5563; text-decoration: line-through; }

    .dot { width: 6px; height: 6px; border-radius: 50%; }
    .dot-ok { background: #10b981; }
    .dot-low { background: #ef4444; }

    @media (max-width: 768px) {
        .header-flex { flex-direction: column; align-items: flex-start; gap: 15px; }
        .list-header { flex-direction: column; align-items: stretch; }
        .search-box { max-width: 100%; }
    }
</style>

<div class="inventory-container">
    
    <!-- HEADER -->
    <div class="header-flex">
        <div class="header-title">
            <h1>Inventory</h1>
        </div>
        <div class="notif-bell">
            <i class="fas fa-bell"></i>
        </div>
    </div>

    <!-- MASTER LIST CARD -->
    <div class="list-card">
        <div class="list-header">
            <div style="display:flex; align-items:center; gap:12px;">
                <div style="background: var(--purple-grad); color:white; width:35px; height:35px; border-radius:10px; display:flex; align-items:center; justify-content:center;">
                    <i class="fas fa-boxes" style="font-size:0.8rem;"></i>
                </div>
                <strong style="color: #1a2b4b;">Stock Level Monitor</strong>
            </div>
            
            <div class="search-box">
                <i class="fas fa-search"></i>
                <input type="text" id="invSearch" placeholder="Search product name or flavor..." onkeyup="filterInventory()">
            </div>
        </div>

        <div class="table-responsive">
            <table class="product-table" id="invTable">
                <thead>
                    <tr>
                        <th>Image</th>
                        <th>Product Name</th>
                        <th>Flavor</th>
                        <th>Category</th>
                        <th>Version</th>
                        <th>ML/MG</th>
                        <th>Cost</th>
                        <th>Price</th>
                        <th>Current Stock</th>
                    </tr>
                </thead>
                <tbody>
                    {% for key, p in products.items() %}
                    <tr>
                        <td>
                            <div class="img-cell">
                                <img src="{{ url_for('static', filename='uploads/' + p.image) if p.image else '' }}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" style="width:100%;height:100%;object-fit:cover;"><div style="display:none;width:100%;height:100%;align-items:center;justify-content:center;color:#cbd5e1;font-size:1.2rem;"><i class="fas fa-image"></i></div>
                            </div>
                        </td>
                        <td class="name-cell">
                            <strong>{{ p.name }}</strong>
                        </td>
                        <td class="flavor-cell">
                            {{ p.flavor or '-' }}
                        </td>
                        <td><span class="badge-cat">{{ p.type }}</span></td>
                        <td>{{ p.version or '-' }}</td>
                        <td>{{ p.mg or '-' }}</td>
                        <td style="color: #64748b; font-size: 0.85rem;">₱{{ "{:,.2f}".format(p.cost) }}</td>
                        <td style="color: #1a2b4b; font-weight: 700;">₱{{ "{:,.2f}".format(p.price) }}</td>
                        <td>
                            {% if p.qty <= 0 %}
                                <span class="stock-pill stock-out">
                                    0 PCS
                                </span>
                            {% elif p.qty < 5 %}
                                <span class="stock-pill stock-low">
                                    <div class="dot dot-low"></div>
                                    {{ p.qty }} PCS (Low)
                                </span>
                            {% else %}
                                <span class="stock-pill stock-ok">
                                    <div class="dot dot-ok"></div>
                                    {{ p.qty }} PCS
                                </span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
    function filterInventory() {
        let input = document.getElementById("invSearch");
        let filter = input.value.toUpperCase();
        let table = document.getElementById("invTable");
        let tr = table.getElementsByTagName("tr");

        for (let i = 1; i < tr.length; i++) {
            // Column 1 is Name, Column 2 is Flavor
            let tdName = tr[i].getElementsByTagName("td")[1];
            let tdFlavor = tr[i].getElementsByTagName("td")[2];
            
            if (tdName && tdFlavor) {
                let nameVal = tdName.textContent || tdName.innerText;
                let flavorVal = tdFlavor.textContent || tdFlavor.innerText;
                
                if (nameVal.toUpperCase().indexOf(filter) > -1 || flavorVal.toUpperCase().indexOf(filter) > -1) {
                    tr[i].style.display = "";
                } else {
                    tr[i].style.display = "none";
                }
            }
        }
    }
</script>
{% endblock %}
"""

TEMPLATES["login.html"] = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Flex Vape | Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --brand-navy: #0f172a;
            --brand-purple: #705194;
            --error-red: #ef4444;
            --bg-soft: #f8fafc;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Inter', sans-serif; }

        body {
            background-color: var(--bg-soft);
            background-image: radial-gradient(circle at 2px 2px, #e2e8f0 1px, transparent 0);
            background-size: 40px 40px;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh;
            padding: 20px;
        }

        /* --- THE SHAKE ANIMATION --- */
        @keyframes shake-animation {
            10%, 90% { transform: translate3d(-1px, 0, 0); }
            20%, 80% { transform: translate3d(2px, 0, 0); }
            30%, 50%, 70% { transform: translate3d(-4px, 0, 0); }
            40%, 60% { transform: translate3d(4px, 0, 0); }
        }

        .shake { animation: shake-animation 0.5s cubic-bezier(.36,.07,.19,.97) both; }

        .login-card {
            background: white;
            width: 100%; max-width: 400px;
            padding: 2.5rem;
            border-radius: 28px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.1);
            border: 1px solid #e2e8f0;
            text-align: center;
        }

        /* --- LOGO DESIGN --- */
        .logo-wrapper {
            width: 100px; height: 100px;
            margin: 0 auto 1.5rem;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            border: 4px solid var(--brand-purple);
            font-size: 2.5rem;
            font-weight: 900;
            color: var(--brand-purple);
            box-shadow: 0 10px 15px -3px rgba(112, 81, 148, 0.2);
        }

        .error-alert {
            background-color: #fef2f2;
            border: 1px solid #fee2e2;
            color: #991b1b;
            padding: 0.8rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            display: flex; align-items: center; justify-content: center;
            gap: 8px; font-size: 0.85rem; font-weight: 600;
        }

        h2 { font-size: 1.6rem; color: var(--brand-navy); font-weight: 800; margin-bottom: 0.5rem; letter-spacing: -0.5px; }
        p.subtitle { color: #64748b; font-size: 0.95rem; margin-bottom: 2rem; }

        .form-group { text-align: left; margin-bottom: 1.25rem; }
        .form-group label { display: block; font-size: 0.75rem; font-weight: 700; color: var(--brand-navy); text-transform: uppercase; margin-bottom: 0.5rem; letter-spacing: 0.5px; }
        
        .input-wrapper { position: relative; }
        .input-wrapper i { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: #94a3b8; font-size: 1rem; transition: 0.2s; }
        
        .form-group input {
            width: 100%; padding: 14px 14px 14px 48px;
            border: 1.5px solid #e2e8f0; border-radius: 14px; font-size: 1rem;
            outline: none; transition: 0.2s; background: #fcfcfd;
        }

        .form-group input:focus { border-color: var(--brand-purple); background: white; box-shadow: 0 0 0 4px rgba(112, 81, 148, 0.1); }
        .form-group input:focus + i { color: var(--brand-purple); }

        .btn-login {
            width: 100%; background: var(--brand-purple); color: white; border: none;
            padding: 16px; border-radius: 14px; font-weight: 700; font-size: 1rem;
            cursor: pointer; transition: 0.3s; margin-top: 1rem;
            box-shadow: 0 10px 15px -3px rgba(112, 81, 148, 0.3);
        }

        .btn-login:hover { background: #5a3d7a; transform: translateY(-1px); box-shadow: 0 20px 25px -5px rgba(112, 81, 148, 0.4); }
        .btn-login:active { transform: translateY(0); }
    </style>
</head>
<body>

    {% with messages = get_flashed_messages() %}
    <div class="login-card {{ 'shake' if messages }}">
        
        <div class="logo-wrapper">F</div>
        
        <h2>F.L.E.X System</h2>
        <p class="subtitle">Enter your admin credentials</p>

        <!-- Display Error Messages -->
        {% if messages %}
            {% for message in messages %}
              <div class="error-alert">
                  <i class="fas fa-circle-exclamation"></i>
                  <span>{{ message }}</span>
              </div>
            {% endfor %}
        {% endif %}

        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <div class="input-wrapper">
                    <i class="fas fa-user"></i>
                    <input type="text" name="username" placeholder="Admin ID" required autofocus>
                </div>
            </div>

            <div class="form-group">
                <label>Password</label>
                <div class="input-wrapper">
                    <i class="fas fa-lock"></i>
                    <input type="password" name="password" placeholder="••••••••" required>
                </div>
            </div>

            <button type="submit" class="btn-login">Secure Sign In</button>
        </form>
    </div>
    {% endwith %}

</body>
</html>
"""

TEMPLATES["products.html"] = """
{% extends "base.html" %}

{% block content %}
<!-- Include Barcode Generation Library -->
<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js"></script>

<style>
    *, *::before, *::after { box-sizing: border-box; }

    :root {
        --brand: #705194;
        --brand-dark: #553c7b;
        --brand-light: #f3e8ff;
        --grad: linear-gradient(135deg, #705194 0%, #553c7b 100%);
        --surface: #ffffff;
        --bg: #f5f4f8;
        --border: #e8e3f0;
        --text: #1a1a2e;
        --muted: #7a7a9a;
        --green: #10b981;
        --red: #ef4444;
        --radius: 16px;
        --radius-sm: 10px;
        --shadow: 0 4px 20px rgba(112,81,148,0.08);
    }

    body { background: var(--bg); }
    .pg { max-width: 900px; margin: 0 auto; padding: 16px; }

    /* PAGE HEADER */
    .pg-header { margin-bottom: 25px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
    .pg-header h1 { font-size: clamp(1.3rem, 5vw, 1.8rem); font-weight: 900; color: var(--text); margin: 0; letter-spacing: -0.5px; }
    .pg-header p { color: var(--muted); margin: 4px 0 0; font-size: 0.85rem; }

    /* CARD */
    .card { background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); border: 1px solid var(--border); margin-bottom: 20px; overflow: hidden; }
    .card-head { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; border-left: 4px solid var(--brand); }
    .card-head .ico { background: var(--grad); color: white; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; flex-shrink: 0; }
    .card-head strong { color: var(--text); font-size: 0.9rem; }

    /* FORM */
    .form-body { padding: 20px; }
    .form-top { display: flex; gap: 20px; margin-bottom: 18px; align-items: center; flex-wrap: wrap; }

    /* Photo */
    .photo-box { width: 110px; height: 110px; border: 2px dashed var(--border); border-radius: var(--radius); display: flex; flex-direction: column; align-items: center; justify-content: center; cursor: pointer; background: var(--bg); overflow: hidden; transition: border-color 0.2s; flex-shrink: 0; }
    .photo-box img { width: 100%; height: 100%; object-fit: cover; display: none; }
    .photo-hint { text-align: center; color: var(--muted); }
    .photo-hint i { font-size: 1.4rem; display: block; margin-bottom: 4px; }
    .photo-hint span { font-size: 0.65rem; text-transform: uppercase; font-weight: 700; }

    /* Fields */
    .right-col { flex: 1; min-width: 180px; }
    .fields-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
    @media (max-width: 480px) { .fields-grid { grid-template-columns: 1fr 1fr; } }

    .field { display: flex; flex-direction: column; gap: 5px; }
    .field label { font-size: 0.6rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.6px; color: var(--muted); }
    .field input, .field select { padding: 10px 12px; background: var(--bg); border: 1.5px solid var(--border); border-radius: var(--radius-sm); font-size: 0.85rem; color: var(--text); width: 100%; }
    .field input:focus, .field select:focus { outline: none; border-color: var(--brand); background: white; }

    .form-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 0 20px; height: 44px; border-radius: var(--radius-sm); font-weight: 700; font-size: 0.85rem; cursor: pointer; border: none; transition: 0.2s; }
    .btn-primary { background: var(--grad); color: white; }
    .btn-ghost { background: var(--bg); color: var(--muted); }

    /* Table */
    .tbl-wrap { overflow-x: auto; }
    .prod-table { width: 100%; border-collapse: collapse; min-width: 700px; }
    .prod-table th { text-align: left; padding: 10px 14px; font-size: 0.6rem; text-transform: uppercase; color: var(--muted); background: var(--bg); border-bottom: 1px solid var(--border); }
    .prod-table td { padding: 11px 14px; border-bottom: 1px solid #eee; vertical-align: middle; font-size: 0.83rem; }
    
    .act-btn { width: 32px; height: 32px; border-radius: 8px; border: 1px solid #e2e8f0; background: white; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: 0.2s; }
    .act-btn:hover { background: #f8fafc; border-color: var(--brand); }
</style>

<div class="pg">
    <div class="pg-header">
        <h1>Products</h1>
        <p>Manage your vape inventory details.</p>
    </div>

    <!-- FORM CARD -->
    <div class="card">
        <div class="card-head">
            <div class="ico"><i class="fas fa-box"></i></div>
            <strong>Product Information</strong>
        </div>

        <form method="POST" enctype="multipart/form-data" id="productForm">
            <input type="hidden" name="editing_key" id="editing_key">
            <input type="hidden" name="action" value="save" id="form_action">
            <input type="hidden" name="barcode" id="barcode">

            <div class="form-body">
                <div class="form-top">
                    <div class="photo-box" onclick="document.getElementById('fileInput').click()">
                        <img id="imgPreview" alt="preview">
                        <div class="photo-hint" id="uploadHint">
                            <i class="fas fa-camera"></i>
                            <span>Upload</span>
                        </div>
                    </div>
                    <input type="file" name="product_image" id="fileInput" hidden onchange="previewImg(this)">

                    <div class="right-col">
                        <div class="field">
                            <label>Product Name / Description</label>
                            <input type="text" name="name" id="name" placeholder="Enter product name..." required>
                        </div>
                    </div>
                </div>

                <div class="fields-grid">
                    <div class="field"><label>Flavor</label><input type="text" name="flavor" id="flavor"></div>
                    <div class="field">
                        <label>Category</label>
                        <select name="type" id="type" required>
                            <option value="pods">Pods</option>
                            <option value="juice">Juice</option>
                            <option value="disposable">Disposable</option>
                            <option value="device">Device</option>
                            <option value="cartridge">Cartridge</option>
                        </select>
                    </div>
                    <div class="field"><label>Version</label><input type="text" name="version" id="version" placeholder="e.g. V2"></div>
                    <div class="field"><label>MG / ML</label><input type="text" name="mg" id="mg" placeholder="e.g. 3% / 30ml"></div>
                    
                    <div class="field" id="qty_group"><label>Initial Qty</label><input type="number" name="quantity" id="quantity" value="0"></div>
                    
                    <div class="field">
                        <label>Barcode ID</label>
                        <div style="display: flex; gap: 4px;">
                            <input type="text" id="barcode_display" placeholder="Scan Barcode" readonly style="background: #e2e8f0;">
                            <button type="button" onclick="scanProductBarcode()" class="btn" style="background: var(--brand); color: white; height: 38px; padding: 0 10px; border-radius: var(--radius-sm); font-size: 0.8rem;">
                                <i class="fas fa-camera"></i>
                            </button>
                        </div>
                    </div>
                    
                    <div class="field"><label>Cost Price ₱</label><input type="number" step="0.01" name="cost" id="cost" required></div>
                    <div class="field"><label>Selling Price ₱</label><input type="number" step="0.01" name="price" id="price" required></div>
                </div>

                <div class="form-footer">
                    <button type="button" class="btn btn-ghost" onclick="resetForm()">Cancel</button>
                    <button type="submit" class="btn-primary btn">Save Product</button>
                </div>
            </div>
        </form>
    </div>

    <!-- MASTERLIST -->
    <div class="card">
        <div class="card-head">
            <strong>Inventory List</strong>
            <div style="margin-left: auto;">
                <input type="text" id="masterSearch" placeholder="Search products..." onkeyup="filterList()" style="padding: 5px 10px; border-radius: 20px; border: 1px solid #ddd; font-size: 0.8rem;">
            </div>
        </div>

        <div class="tbl-wrap">
            <table class="prod-table" id="masterTable">
                <thead>
                    <tr>
                        <th>Product Name</th>
                        <th>Stock</th>
                        <th>Price</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for key, p in products.items() %}
                    <tr>
                        <td>
                            <strong>{{ p.name }}</strong><br>
                            <small style="color:var(--muted)">{{ p.flavor or '' }} {{ '| ' + p.mg if p.mg else '' }}</small>
                        </td>
                        <td style="font-weight:bold; color: {{ 'red' if p.qty < 5 else 'green' }}">{{ p.qty }}</td>
                        <td>₱{{ "{:,.2f}".format(p.price) }}</td>
                        <td>
                            <div style="display:flex;gap:5px;">
                                <button class="act-btn" onclick="editProduct('{{ key }}')" style="color:blue;"><i class="fas fa-edit"></i></button>
                                <button class="act-btn" onclick="delProduct('{{ key }}')" style="color:red;"><i class="fas fa-trash"></i></button>
                            </div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
const productsData = {{ products|tojson }};

function previewImg(input) {
    if (!input.files?.[0]) return;
    const r = new FileReader();
    r.onload = e => {
        const img = document.getElementById('imgPreview');
        img.src = e.target.result; img.style.display = 'block';
        document.getElementById('uploadHint').style.display = 'none';
    };
    r.readAsDataURL(input.files[0]);
}

function scanProductBarcode() {
    startFSScanner((decodedText) => {
        document.getElementById('barcode_display').value = decodedText;
        document.getElementById('barcode').value = decodedText;
    });
}

function editProduct(key) {
    const p = productsData[key];
    document.getElementById('editing_key').value = key;
    document.getElementById('barcode').value = p.barcode || '';
    document.getElementById('barcode_display').value = p.barcode || 'Generated';
    document.getElementById('name').value = p.name;
    document.getElementById('flavor').value = p.flavor || '';
    document.getElementById('type').value = p.type;
    document.getElementById('version').value = p.version || '';
    document.getElementById('mg').value = p.mg || '';
    document.getElementById('cost').value = p.cost;
    document.getElementById('price').value = p.price;
    document.getElementById('qty_group').style.display = 'none';
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resetForm() {
    document.getElementById('productForm').reset();
    document.getElementById('editing_key').value = '';
    document.getElementById('barcode').value = '';
    document.getElementById('barcode_display').value = '';
    document.getElementById('qty_group').style.display = '';
    document.getElementById('imgPreview').style.display = 'none';
    document.getElementById('uploadHint').style.display = 'flex';
}

function delProduct(key) {
    if (!confirm('Delete this product?')) return;
    document.getElementById('editing_key').value = key;
    document.getElementById('form_action').value = 'delete';
    document.getElementById('productForm').submit();
}

function filterList() {
    const q = document.getElementById('masterSearch').value.toUpperCase();
    const rows = document.querySelectorAll('#masterTable tbody tr');
    rows.forEach(r => {
        r.style.display = r.innerText.toUpperCase().includes(q) ? '' : 'none';
    });
}
</script>
{% endblock %}
"""

TEMPLATES["history.html"] = """
{% extends "base.html" %}

{% block content %}
<style>
    :root {
        --brand-navy: #0f172a;
        --brand-purple: #6366f1;
        --brand-green: #10b981;
        --bg-main: #f8fafc;
        --border-color: #e2e8f0;
        --text-main: #1e293b;
        --text-muted: #64748b;
        --card-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    }

    /* Professional Reset & Wrapper */
    .history-wrapper {
        max-width: 1200px;
        margin: 0 auto;
        padding: 2rem 1rem;
        font-family: 'Inter', -apple-system, sans-serif;
        background-color: var(--bg-main);
        min-height: 100vh;
    }

    /* Top Navigation Area */
    .top-bar {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        margin-bottom: 2rem;
        border-bottom: 1px solid var(--border-color);
        padding-bottom: 1.5rem;
    }

    .btn-back {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--text-muted);
        text-decoration: none;
        font-size: 0.875rem;
        font-weight: 500;
        padding: 0.5rem 0.75rem;
        border-radius: 6px;
        transition: all 0.2s ease;
        background: white;
        border: 1px solid var(--border-color);
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }

    .btn-back:hover {
        background: #f1f5f9;
        color: var(--brand-navy);
        border-color: #cbd5e1;
    }

    .pg-title-group h1 {
        font-size: 1.875rem;
        font-weight: 800;
        color: var(--brand-navy);
        letter-spacing: -0.025em;
        margin: 0;
    }

    .pg-title-group p {
        color: var(--text-muted);
        font-size: 0.95rem;
        margin-top: 0.25rem;
    }

    /* --- GRID SYSTEM --- */
    .history-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 1.5rem;
    }

    @media (min-width: 1024px) {
        .history-grid {
            grid-template-columns: 2fr 1fr;
        }
    }

    /* --- CARD STYLING --- */
    .h-card {
        background: #ffffff;
        border-radius: 12px;
        border: 1px solid var(--border-color);
        box-shadow: var(--card-shadow);
        overflow: hidden;
        display: flex;
        flex-direction: column;
    }

    .h-card-header {
        padding: 1.25rem 1.5rem;
        border-bottom: 1px solid var(--border-color);
        background: #fafafa;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .h-card-title {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        font-weight: 700;
        font-size: 0.95rem;
        color: var(--brand-navy);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* --- MODERN TABLE --- */
    .table-container {
        width: 100%;
        overflow-x: auto;
    }

    .h-table {
        width: 100%;
        border-collapse: collapse;
        text-align: left;
    }

    .h-table th {
        background: #ffffff;
        padding: 1rem 1.5rem;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        color: var(--text-muted);
        border-bottom: 1px solid var(--border-color);
    }

    .h-table tr {
        transition: background 0.1s ease;
    }

    .h-table tr:hover {
        background: #f8fafc;
    }

    .h-table td {
        padding: 1.25rem 1.5rem;
        border-bottom: 1px solid #f1f5f9;
        font-size: 0.9rem;
        color: var(--text-main);
    }

    /* Component Details */
    .date-cell {
        font-weight: 600;
        color: var(--brand-navy);
    }

    .count-badge {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        background: #eff6ff;
        color: #2563eb;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 700;
        border: 1px solid #dbeafe;
    }

    .revenue-text {
        font-family: 'Monaco', 'Consolas', monospace;
        font-weight: 700;
        color: var(--brand-green);
        font-size: 1rem;
    }

    .revenue-secondary {
        font-family: 'Monaco', 'Consolas', monospace;
        font-weight: 700;
        color: var(--brand-navy);
    }

    .empty-state {
        padding: 4rem 2rem;
        text-align: center;
        color: var(--text-muted);
    }

    .info-footer {
        padding: 1rem;
        background: #f1f5f9;
        border-top: 1px solid var(--border-color);
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.75rem;
        color: var(--text-muted);
    }

    @media (max-width: 640px) {
        .top-bar {
            flex-direction: column-reverse;
            align-items: flex-start;
            gap: 1rem;
        }
        .revenue-text { font-size: 0.85rem; }
    }
</style>

<div class="history-wrapper">
    
    <!-- HEADER SECTION -->
    <div class="top-bar">
        <div class="pg-title-group">
            <p>Archive & Analytics</p>
            <h1>Business History</h1>
        </div>
        <a href="/" class="btn-back">
            <i class="fa-solid fa-arrow-left"></i>
            <span>Back to Dashboard</span>
        </a>
    </div>

    <div class="history-grid">
        
        <!-- MAIN SECTION: DAILY LOGS -->
        <div class="h-card">
            <div class="h-card-header">
                <div class="h-card-title">
                    <i class="fa-solid fa-calendar-check" style="color: var(--brand-purple);"></i>
                    Daily Performance Log
                </div>
            </div>
            
            <div class="table-container">
                <table class="h-table">
                    <thead>
                        <tr>
                            <th>Reporting Date</th>
                            <th style="text-align:center;">Txn Count</th>
                            <th style="text-align:right;">Gross Revenue</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for log in daily %}
                        <tr>
                            <td class="date-cell">{{ log.day }}</td>
                            <td style="text-align:center;">
                                <span class="count-badge">{{ log.count }} Sales</span>
                            </td>
                            <td style="text-align:right;">
                                <span class="revenue-text">₱{{ "{:,.2f}".format(log.revenue) }}</span>
                            </td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="3" class="empty-state">
                                <i class="fa-solid fa-inbox fa-2x" style="margin-bottom: 1rem; opacity: 0.3;"></i>
                                <p>No historical records found for the current period.</p>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- SIDE SECTION: MONTHLY TRENDS -->
        <div class="h-card">
            <div class="h-card-header">
                <div class="h-card-title">
                    <i class="fa-solid fa-chart-line" style="color: var(--brand-purple);"></i>
                    Monthly Growth
                </div>
            </div>

            <div class="table-container">
                <table class="h-table">
                    <thead>
                        <tr>
                            <th>Period</th>
                            <th style="text-align: right;">Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for log in monthly %}
                        <tr>
                            <td>
                                <div style="font-weight: 700; color: var(--brand-navy);">{{ log.month }}</div>
                                <div style="font-size: 0.75rem; color: var(--text-muted);">Fiscal Year {{ log.year }}</div>
                            </td>
                            <td style="text-align: right;">
                                <span class="revenue-secondary">₱{{ "{:,.2f}".format(log.revenue) }}</span>
                            </td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="2" class="empty-state">No monthly data.</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            
            <div class="info-footer">
                <i class="fa-solid fa-circle-info"></i>
                Data is finalized daily at 23:59 (Server Time).
            </div>
        </div>

    </div>
</div>
{% endblock %}
"""

TEMPLATES["reports.html"] = """
{% extends "base.html" %}

{% block content %}
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>

<style>
    :root {
        --brand-navy: #162135;
        --brand-purple: #705194;
        --brand-green: #10b981;
        --brand-red: #ef4444;
        --soft-bg: #f8fafc;
        --border-light: #e2e8f0;
    }

    /* --- PAGE UI WRAPPER --- */
    .report-ui-wrapper { 
        max-width: 900px; 
        margin: 0 auto; 
        padding: 10px; 
    }

    /* --- RESPONSIVE CONTROLS --- */
    .report-controls {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: white;
        padding: 12px;
        border-radius: 12px;
        margin-bottom: 20px;
        border: 1px solid var(--border-light);
        flex-wrap: wrap; 
        gap: 12px;
    }

    .period-selector { 
        display: flex; 
        background: #f1f5f9; 
        padding: 4px; 
        border-radius: 8px; 
        flex: 1; 
        min-width: 200px; 
    }
    .period-btn { 
        text-decoration: none; 
        padding: 8px 12px; 
        flex: 1; 
        text-align: center; 
        border-radius: 6px; 
        font-size: 0.8rem; 
        font-weight: 600; 
        color: #64748b; 
        transition: 0.2s; 
    }
    .period-btn.active { background: white; color: var(--brand-purple); box-shadow: 0 2px 4px rgba(0,0,0,0.05); }

    .btn-group { 
        display: flex; 
        gap: 8px; 
        flex: 1; 
        justify-content: flex-end; 
        min-width: 200px; 
    }
    .btn-action { 
        flex: 1; 
        border: none; 
        padding: 10px; 
        border-radius: 8px; 
        font-weight: 700; 
        cursor: pointer; 
        display: flex; 
        align-items: center; 
        justify-content: center; 
        gap: 6px; 
        font-size: 0.8rem; 
        color: white; 
    }
    .btn-pdf { background: #475569; }
    .btn-img { background: var(--brand-purple); }

    /* --- THE OFFICIAL REPORT DOCUMENT --- */
    #report-capture-area {
        background: white;
        width: 100%;
        margin: 0 auto;
        padding: 5vw; /* Fluid padding based on screen width */
        color: var(--brand-navy);
        font-family: 'Inter', sans-serif;
        border: 1px solid var(--border-light);
        position: relative;
        box-sizing: border-box;
    }

    /* CENTERED LOGO HEADER */
    .doc-header {
        text-align: center;
        border-bottom: 2px solid var(--brand-navy);
        padding-bottom: 20px;
        margin-bottom: 30px;
    }

    .brand-info h2 { margin: 0; font-size: clamp(1.1rem, 4vw, 1.6rem); font-weight: 800; letter-spacing: 1px; }
    .brand-info p { margin: 5px 0 0; font-size: clamp(0.7rem, 2vw, 0.85rem); color: #64748b; text-transform: uppercase; }
    .report-type-label { margin-top: 15px; font-size: clamp(0.9rem, 3vw, 1.1rem); font-weight: 700; color: var(--brand-purple); text-transform: uppercase; }
    .report-date { font-size: 0.8rem; color: #94a3b8; margin-top: 5px; }

    /* Highlights Section */
    .report-grid { 
        display: grid; 
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); 
        gap: 15px; 
        margin-bottom: 30px; 
    }
    .stat-card { background: var(--soft-bg); padding: 15px; border-radius: 12px; border: 1px solid var(--border-light); text-align: center;}
    .stat-card label { display: block; font-size: 0.6rem; font-weight: 800; color: #94a3b8; text-transform: uppercase; margin-bottom: 5px; }
    .stat-card .value { font-size: clamp(1.1rem, 4vw, 1.6rem); font-weight: 800; }
    .stat-card .value.green { color: var(--brand-green); }

    /* Movement Table */
    .table-responsive {
        width: 100%;
        overflow-x: auto; 
        -webkit-overflow-scrolling: touch;
        margin-bottom: 25px;
        border-radius: 8px;
    }
    
    /* Swipe Hint for Mobile */
    .swipe-hint { display: none; font-size: 0.65rem; color: #94a3b8; margin-bottom: 5px; text-align: right; font-style: italic; }

    .report-table { width: 100%; border-collapse: collapse; min-width: 500px; }
    .report-table th { background: #f1f5f9; text-align: left; padding: 10px; font-size: 0.7rem; color: #475569; border: 1px solid var(--border-light); }
    .report-table td { padding: 10px; font-size: 0.8rem; border: 1px solid var(--border-light); }

    /* Alerts */
    .section-heading { font-size: 0.75rem; font-weight: 800; text-transform: uppercase; margin-bottom: 12px; color: #475569; display: flex; align-items: center; gap: 8px;}
    .section-heading::after { content: ""; flex: 1; height: 1px; background: var(--border-light); }
    .warning-box { background: #fff1f2; border: 1px solid #ffe4e6; border-radius: 12px; padding: 12px; }
    .warning-item { font-size: 0.75rem; font-weight: 600; color: #991b1b; display: flex; justify-content: space-between; padding: 4px 0; }

    .doc-footer { margin-top: 30px; padding-top: 15px; border-top: 1px solid var(--border-light); display: flex; justify-content: space-between; font-size: 0.6rem; color: #94a3b8; flex-wrap: wrap; gap: 8px; }

    /* --- MOBILE BREAKPOINT --- */
    @media (max-width: 600px) {
        .report-ui-wrapper { padding: 5px; }
        .report-controls { padding: 10px; border-radius: 0; margin-left: -5px; margin-right: -5px; }
        .swipe-hint { display: block; }
        #report-capture-area { padding: 20px 15px; border-left: none; border-right: none; }
        .btn-group { min-width: 100%; }
        .period-selector { min-width: 100%; }
    }

    /* --- PRINT FIXES --- */
    @media print {
        nav, .sidebar, .mobile-header, .mobile-toggle, .no-print, header, .swipe-hint { display: none !important; }
        body { background: white; margin: 0; padding: 0; }
        .main-content { margin-left: 0 !important; width: 100% !important; padding: 0 !important; }
        #report-capture-area { border: none; box-shadow: none; padding: 40px; width: 100%; }
        .table-responsive { overflow: visible !important; }
    }
</style>

<div class="report-ui-wrapper">
    
    <!-- Controls -->
    <div class="report-controls no-print">
        <div class="period-selector">
            <a href="/reports?period=daily" class="period-btn {{ 'active' if period == 'daily' }}">Daily Audit</a>
            <a href="/reports?period=weekly" class="period-btn {{ 'active' if period == 'weekly' }}">Weekly Audit</a>
        </div>

        <div class="btn-group">
            <button onclick="window.print()" class="btn-action btn-pdf">
                <i class="fas fa-file-pdf"></i> PDF
            </button>
            <button onclick="downloadReportImage()" class="btn-action btn-img">
                <i class="fas fa-image"></i> IMAGE
            </button>
        </div>
    </div>

    <!-- The Document -->
    <div id="report-capture-area">
        <div class="doc-header">
            <div class="brand-info">
                <h2>F.L.E.X VAPE SHOP</h2>
                <p>Inventory Management System</p>
            </div>
            
            <div class="report-type-label">{{ report_label }}</div>
            <div class="report-date">Issued: {{ date }}</div>
        </div>

        <div class="report-grid">
            <div class="stat-card">
                <label>Gross Revenue</label>
                <div class="value green">₱{{ "{:,.2f}".format(revenue) }}</div>
            </div>
            <div class="stat-card">
                <label>Sales Volume</label>
                <div class="value">{{ sales_count }} Sales</div>
            </div>
        </div>

        <div class="section-heading">Stock Movement Summary</div>
        <div class="swipe-hint">Swipe table to see more &rarr;</div>
        <div class="table-responsive">
            <table class="report-table">
                <thead>
                    <tr>
                        <th>Product & Flavor</th>
                        <th style="text-align:center;">Open</th>
                        <th style="text-align:center;">In</th>
                        <th style="text-align:center;">Out</th>
                        <th style="text-align:center;">End</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in movement %}
                    <tr>
                        <td><strong>{{ item.name }}</strong></td>
                        <td style="text-align:center;">{{ item.open }}</td>
                        <td style="text-align:center; color: var(--brand-green); font-weight: 700;">+{{ item.new }}</td>
                        <td style="text-align:center; color: var(--brand-red); font-weight: 700;">-{{ item.sold }}</td>
                        <td style="text-align:center; font-weight: 700;">{{ item.end }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        {% if low_stocks %}
        <div class="section-heading" style="color: var(--brand-red);">Critical Stock Warnings</div>
        <div class="warning-box">
            {% for cat, items in low_stocks.items() %}
                {% for item in items %}
                <div class="warning-item">
                    <span>{{ item.name }} ({{ item.flavor }})</span>
                    <span>{{ item.qty }} UNITS LEFT</span>
                </div>
                {% endfor %}
            {% endfor %}
        </div>
        {% endif %}

        <div class="doc-footer">
            <span>Auth: {{ now }}</span>
            <span>F.L.E.X System &bull; Inventory Record</span>
        </div>
    </div>
</div>

<script>
async function downloadReportImage() {
    const reportArea = document.getElementById('report-capture-area');
    const downloadBtn = document.querySelector('.btn-img');
    
    downloadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>...';
    downloadBtn.disabled = true;

    try {
        const canvas = await html2canvas(reportArea, {
            scale: 3, 
            useCORS: true,
            backgroundColor: "#ffffff",
        });

        const link = document.createElement('a');
        link.href = canvas.toDataURL("image/png", 1.0);
        link.download = `FLEX_Report_{{ date }}.png`;
        link.click();
    } catch (err) {
        alert("Export failed.");
    } finally {
        downloadBtn.innerHTML = '<i class="fas fa-image"></i> IMAGE';
        downloadBtn.disabled = false;
    }
}
</script>
{% endblock %}
"""

TEMPLATES["sales.html"] = """
{% extends "base.html" %}

{% block content %}
<style>
    *, *::before, *::after { box-sizing: border-box; }

    :root {
        --brand: #705194;
        --brand-dark: #553c7b;
        --brand-light: #f3e8ff;
        --grad: linear-gradient(135deg, #705194 0%, #553c7b 100%);
        --surface: #ffffff;
        --bg: #f5f4f8;
        --border: #e8e3f0;
        --text: #1a1a2e;
        --muted: #7a7a9a;
        --green: #10b981;
        --red: #ef4444;
        --radius: 16px;
        --radius-sm: 10px;
        --shadow: 0 4px 20px rgba(112,81,148,0.08);
    }

    body { background: var(--bg); }
    .pg { max-width: 900px; margin: 0 auto; padding: 16px; }

    /* PAGE HEADER */
    .pg-header { margin-bottom: 20px; }
    .pg-header h1 { font-size: clamp(1.3rem, 5vw, 1.8rem); font-weight: 900; color: var(--text); margin: 0; letter-spacing: -0.5px; }
    .pg-header p { color: var(--muted); margin: 2px 0 0; font-size: 0.82rem; }

    /* CARD */
    .card { background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); border: 1px solid var(--border); margin-bottom: 20px; overflow: hidden; }
    .card-head { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; border-left: 4px solid var(--brand); }
    .card-head .ico { background: var(--grad); color: white; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; flex-shrink: 0; }
    .card-head strong { color: var(--text); font-size: 0.9rem; }

    /* FORM BODY */
    .form-body { padding: 20px; }

    .selected-badge {
        background: #f0fdf4; border: 1.5px solid #6ee7b7; border-radius: var(--radius-sm);
        padding: 10px 14px; font-size: 0.82rem; color: #065f46; font-weight: 700;
        display: none; align-items: center; gap: 8px; margin-bottom: 15px;
    }
    .selected-badge.show { display: flex; }

    .fields-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
    @media (max-width: 450px) { .fields-row { grid-template-columns: 1fr; } }

    .field { display: flex; flex-direction: column; gap: 5px; }
    .field label { font-size: 0.6rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.6px; color: var(--muted); }
    .field input { padding: 10px 12px; background: var(--bg); border: 1.5px solid var(--border); border-radius: var(--radius-sm); font-size: 0.9rem; color: var(--text); width: 100%; }
    .field input:focus { outline: none; border-color: var(--brand); background: white; }

    .total-box {
        background: linear-gradient(135deg, #ede9fe, var(--brand-light));
        border: 1.5px solid #c4b5fd;
        border-radius: var(--radius-sm);
        padding: 12px;
        font-size: 1.3rem;
        font-weight: 900;
        color: #4c1d95;
        text-align: center;
        display: flex; align-items: center; justify-content: center;
    }

    /* Search results */
    .search-wrap { position: relative; }
    .search-results {
        position: absolute; top: 100%; left: 0; right: 0;
        background: white; border-radius: var(--radius-sm);
        box-shadow: 0 10px 30px rgba(0,0,0,0.12);
        max-height: 200px; overflow-y: auto;
        z-index: 200; display: none; margin-top: 4px; border: 1.5px solid var(--border);
    }
    .s-item { padding: 10px 14px; cursor: pointer; border-bottom: 1px solid var(--bg); }
    .s-item:hover { background: var(--brand-light); }
    .s-item strong { display: block; font-size: 0.85rem; color: var(--text); }
    .s-item small { font-size: 0.72rem; color: var(--muted); }

    .form-footer { display: flex; gap: 10px; margin-top: 20px; }
    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 0 20px; height: 46px; border-radius: var(--radius-sm); font-weight: 700; font-size: 0.88rem; cursor: pointer; border: none; transition: 0.2s; }
    .btn-primary { background: var(--grad); color: white; flex: 1; }
    .btn-primary:disabled { opacity: 0.45; pointer-events: none; }
    .btn-ghost { background: var(--bg); color: var(--muted); }

    /* HISTORY */
    .log-table { width: 100%; border-collapse: collapse; }
    .log-table th { text-align: left; padding: 10px 14px; font-size: 0.6rem; text-transform: uppercase; color: var(--muted); background: var(--bg); border-bottom: 1px solid var(--border); }
    .log-table td { padding: 11px 14px; border-bottom: 1px solid var(--bg); font-size: 0.83rem; }
    .log-table tr:hover td { background: #faf9ff; }

    .toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(80px); background: #1a1a2e; color: white; padding: 12px 22px; border-radius: 50px; font-size: 0.83rem; font-weight: 600; box-shadow: 0 8px 30px rgba(0,0,0,0.2); z-index: 9999; opacity: 0; transition: all 0.3s ease; }
    .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
</style>

<div class="pg">
    <div class="pg-header">
        <h1>Sales</h1>
        <p>Search for a product to record a transaction.</p>
    </div>

    <!-- TRANSACTION CARD -->
    <div class="card">
        <div class="card-head">
            <div class="ico"><i class="fas fa-shopping-cart"></i></div>
            <strong>New Transaction</strong>
        </div>

        <form method="POST" id="saleForm" autocomplete="off">
            <div class="form-body">
                <!-- Selected Product Badge -->
                <div class="selected-badge" id="selectedBadge">
                    <i class="fas fa-check-circle"></i>
                    <span id="badgeText">Product selected</span>
                </div>

                <!-- Search Field -->
                <div class="field search-wrap">
                    <label>Search Product Name</label>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <input type="text" id="productSearch" placeholder="Type product name or flavor..." oninput="filterProducts()" style="flex: 1;">
                        <button type="button" onclick="triggerBarcodeScanner()" class="btn" style="background: var(--brand); color: white; width: 46px; height: 46px; padding: 0; display: flex; align-items: center; justify-content: center; border-radius: var(--radius-sm);">
                            <i class="fas fa-camera"></i>
                        </button>
                    </div>
                    <input type="hidden" name="product_key" id="hiddenKey" required>
                    <div id="searchResults" class="search-results"></div>
                </div>

                <!-- Qty and Total Row -->
                <div class="fields-row">
                    <div class="field">
                        <label>Quantity</label>
                        <input type="number" name="quantity" id="qtyInput" value="" min="1" oninput="calcTotal()">
                    </div>
                    <div class="field">
                        <label>Total Price</label>
                        <div class="total-box" id="totalBox">₱ 0.00</div>
                    </div>
                </div>

                <div class="form-footer">
                    <button type="button" class="btn btn-ghost" onclick="clearSale()">Clear</button>
                    <button type="submit" class="btn btn-primary" id="saleBtn" disabled>
                        <i class="fas fa-check-circle"></i> Complete Sale
                    </button>
                </div>
            </div>
        </form>
    </div>

    <!-- RECENT SALES -->
    <div class="card">
        <div class="card-head">
            <div class="ico"><i class="fas fa-history"></i></div>
            <strong>Recent History</strong>
        </div>
        <div style="overflow-x: auto;">
            <table class="log-table">
                <thead>
                    <tr><th>Time</th><th>Product</th><th>Qty</th><th>Total</th></tr>
                </thead>
                <tbody>
                    {% for log in logs %}
                    <tr>
                        <td style="color:var(--muted); font-size:0.75rem;">{{ log.date.strftime('%H:%M') }}</td>
                        <td>
                            <strong>{{ log.name }}</strong><br>
                            <small style="color:var(--brand);">{{ log.flavor }}</small>
                        </td>
                        <td>{{ log.qty }}</td>
                        <td style="color:var(--green); font-weight:800;">₱{{ "{:,.2f}".format(log.qty * log.price) }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
const productsData = {{ products|tojson }};

function showToast(msg, color = '#10b981') {
    const t = document.getElementById('toast');
    t.textContent = msg; t.style.borderBottom = `3px solid ${color}`;
    t.className = 'toast show';
    setTimeout(() => { t.className = 'toast'; }, 2500);
}

function selectItem(id, label, price, stock) {
    document.getElementById('hiddenKey').value = id;
    document.getElementById('productSearch').value = label;
    document.getElementById('searchResults').style.display = 'none';

    document.getElementById('badgeText').textContent = `${label} (In Stock: ${stock})`;
    document.getElementById('selectedBadge').classList.add('show');

    document.getElementById('qtyInput').dataset.price = price;
    document.getElementById('qtyInput').max = stock;
    document.getElementById('qtyInput').value = 1;
    document.getElementById('saleBtn').disabled = false;
    calcTotal();
}

function filterProducts() {
    const q = document.getElementById('productSearch').value.toLowerCase();
    const div = document.getElementById('searchResults');
    document.getElementById('saleBtn').disabled = true;

    if (q.length < 1) { div.style.display = 'none'; return; }

    const matches = Object.entries(productsData).filter(([id, p]) =>
        p.name.toLowerCase().includes(q) || (p.flavor||'').toLowerCase().includes(q)
    );

    div.innerHTML = matches.map(([id, p]) => `
        <div class="s-item" onclick="selectItem('${id}','${p.name} - ${p.flavor}',${p.price},${p.qty})">
            <strong>${p.name} <span style="color:var(--brand)">${p.flavor||''}</span></strong>
            <small>Stock: ${p.qty} | ₱${p.price.toLocaleString()}</small>
        </div>
    `).join('');
    div.style.display = matches.length ? 'block' : 'none';
}

function triggerBarcodeScanner() {
    startFSScanner((decodedText) => {
        const match = Object.entries(productsData).find(([id, p]) => p.barcode === decodedText);
        if (match) {
            const [id, p] = match;
            selectItem(id, `${p.name} - ${p.flavor}`, p.price, p.qty);
            showToast(`Product linked: ${p.name}`);
        } else {
            showToast(`Barcode ID ${decodedText} not detected in inventory.`, '#ef4444');
        }
    });
}

function calcTotal() {
    const qty = parseInt(document.getElementById('qtyInput').value) || 0;
    const price = parseFloat(document.getElementById('qtyInput').dataset.price) || 0;
    document.getElementById('totalBox').textContent = `₱ ${(qty * price).toLocaleString(undefined,{minimumFractionDigits:2})}`;
}

function clearSale() {
    document.getElementById('hiddenKey').value = '';
    document.getElementById('productSearch').value = '';
    document.getElementById('qtyInput').value = 1;
    document.getElementById('totalBox').textContent = '₱ 0.00';
    document.getElementById('selectedBadge').classList.remove('show');
    document.getElementById('saleBtn').disabled = true;
}

window.addEventListener('click', e => {
    if (!e.target.matches('#productSearch')) document.getElementById('searchResults').style.display = 'none';
});
</script>
{% endblock %}
"""

# --- 7. ASSIGN DICTLOADER TO JINJA WORKFLOW ---
app.jinja_loader = DictLoader(TEMPLATES)

# --- 8. DATABASE AUTO INITIALIZE AND HOST EXECUTION ---
migrate = Migrate(app, db)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')