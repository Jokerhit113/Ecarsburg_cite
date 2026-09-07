from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from database import engine, Base, SessionLocal
from models import Company, UserAction
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import io
import base64
from datetime import datetime, timedelta
from models import Company, ClickEvent
from sqlalchemy import func

# Создаем таблицы в базе данных (если их еще нет)
Base.metadata.create_all(bind=engine)

# Инициализация Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-in-production'  # Замени на случайную строку!

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Куда редиректить, если пользователь не авторизован


@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.query(Company).get(int(user_id))
    finally:
        db.close()


# ==================== РОУТЫ ====================

@app.route('/')
def index():
    """Главная страница сайта-визитки"""
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        db = SessionLocal()
        try:
            user = db.query(Company).filter(Company.email == email).first()

            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                flash('Вы успешно вошли в систему!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Неверный email или пароль', 'error')
        finally:
            db.close()

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Страница регистрации"""
    if request.method == 'POST':
        name = request.form.get('name')
        slug = request.form.get('slug')
        email = request.form.get('email')
        password = request.form.get('password')

        # Валидация slug
        import re
        if not re.match(r'^[a-z0-9_-]+$', slug):
            flash('Название может содержать только латинские буквы, цифры, дефис и подчеркивание.', 'error')
            return redirect(url_for('register'))

        db = SessionLocal()
        try:
            # Проверка уникальности email
            if db.query(Company).filter(Company.email == email).first():
                flash('Email уже зарегистрирован', 'error')
                return redirect(url_for('register'))

            # Проверка уникальности slug
            if db.query(Company).filter(Company.slug == slug).first():
                flash('Это название уже занято. Придумайте другое.', 'error')
                return redirect(url_for('register'))

            # Создание нового пользователя
            new_company = Company(
                name=name,
                slug=slug,
                email=email,
                password_hash=generate_password_hash(password)
            )
            db.add(new_company)
            db.commit()

            flash('Регистрация успешна! Теперь вы можете войти.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.rollback()
            flash(f'Ошибка при регистрации: {str(e)}', 'error')
        finally:
            db.close()

    return render_template('register.html')


# @app.route('/dashboard')
# @login_required
# def dashboard():
#     """Личный кабинет"""
#     return render_template('dashboard.html', user=current_user)


@app.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))



# ==================== РЕФЕРАЛЬНАЯ СИСТЕМА ====================

@app.route('/company/<slug>')
def track_referral(slug):
    """Отслеживание перехода по реферальной ссылке"""
    db = SessionLocal()
    try:
        # Ищем компанию по slug
        company = db.query(Company).filter(Company.slug == slug).first()
        if not company:
            flash('Компания не найдена', 'error')
            return redirect(url_for('index'))

        # Получаем IP пользователя
        user_ip = request.remote_addr

        # Защита от накрутки: проверяем, не кликал ли этот IP за последние 24 часа
        one_day_ago = datetime.utcnow() - timedelta(days=1)
        recent_click = db.query(ClickEvent).filter(
            ClickEvent.company_id == company.id,
            ClickEvent.ip_address == user_ip,
            ClickEvent.clicked_at >= one_day_ago
        ).first()

        # Если клика не было - сохраняем
        if not recent_click:
            new_click = ClickEvent(
                company_id=company.id,
                ip_address=user_ip,
                user_agent=request.headers.get('User-Agent', '')[:255]
            )
            db.add(new_click)

            # Также сохраняем в общую таблицу действий
            user_action = UserAction(
                ip_address=user_ip,
                user_agent=request.headers.get('User-Agent', '')[:500],
                action_type='referral_click',
                action_detail=company.slug,
                referral_slug=company.slug,
                page_url=request.url
            )
            db.add(user_action)

            db.commit()

        # Редирект на главную с параметром ref (чтобы JavaScript знал, откуда пришел)
        return redirect(url_for('index', ref=slug))
    finally:
        db.close()


# ==================== ЛИЧНЫЙ КАБИНЕТ ====================

@app.route('/dashboard')
@login_required
def dashboard():
    """Личный кабинет с реферальной ссылкой и QR-кодом"""
    db = SessionLocal()
    try:
        # Формируем реферальную ссылку
        referral_link = request.host_url.rstrip('/') + url_for('track_referral', slug=current_user.slug)

        # Генерируем QR-код
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(referral_link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # Конвертируем в Base64
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
        qr_data_uri = f"data:image/png;base64,{qr_base64}"

        # Считаем уникальные клики для текущей компании
        total_clicks = db.query(ClickEvent).filter_by(company_id=current_user.id).count()

        return render_template(
            'dashboard.html',
            user=current_user,
            referral_link=referral_link,
            qr_code=qr_data_uri,
            total_clicks=total_clicks
        )
    finally:
        db.close()


# ==================== АДМИН-ПАНЕЛЬ ====================

def admin_required(f):
    """Декоратор для проверки прав администратора"""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('У вас нет прав администратора', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)

    return decorated_function


@app.route('/admin/leaderboard')
@admin_required
def admin_leaderboard():
    """Таблица лидеров для администратора"""
    db = SessionLocal()
    try:
        # Запрос с группировкой и подсчетом кликов
        leaderboard_data = db.query(
            Company.name,
            Company.slug,
            Company.email,
            func.count(ClickEvent.id).label('total_clicks')
        ).outerjoin(ClickEvent, Company.id == ClickEvent.company_id) \
            .group_by(Company.id, Company.name, Company.slug, Company.email) \
            .order_by(func.count(ClickEvent.id).desc()) \
            .all()

        # Считаем общее количество компаний
        total_companies = db.query(Company).count()

        return render_template(
            'admin_leaderboard.html',
            leaderboard=leaderboard_data,
            total_companies=total_companies
        )
    finally:
        db.close()


from flask import jsonify


@app.route('/track-action', methods=['POST'])
def track_action():
    """Принимает события от JavaScript и сохраняет в БД"""
    try:
        data = request.get_json()

        db = SessionLocal()
        try:
            action = UserAction(
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent', '')[:500],
                action_type=data.get('action_type', 'unknown'),
                action_detail=data.get('action_detail', ''),
                referral_slug=data.get('referral_slug', ''),
                page_url=data.get('page_url', '')
            )
            db.add(action)
            db.commit()

            return jsonify({'status': 'success'})
        finally:
            db.close()
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/admin/analytics')
@admin_required
def admin_analytics():
    """Подробная аналитика действий пользователей"""
    db = SessionLocal()
    try:
        # Статистика по типам действий
        action_stats = db.query(
            UserAction.action_type,
            UserAction.action_detail,
            func.count(UserAction.id).label('count')
        ).group_by(UserAction.action_type, UserAction.action_detail) \
            .order_by(func.count(UserAction.id).desc()) \
            .all()

        # Последние 50 действий
        recent_actions = db.query(UserAction) \
            .order_by(UserAction.created_at.desc()) \
            .limit(50) \
            .all()

        return render_template(
            'admin_analytics.html',
            action_stats=action_stats,
            recent_actions=recent_actions
        )
    finally:
        db.close()

# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    app.run(debug=True)