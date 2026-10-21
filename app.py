from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from database import engine, Base, SessionLocal
from models import Company, UserAction, ClickEvent, Bonus, SiteSetting, ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_PARTNER
from sqlalchemy import text as sa_text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import qrcode
import io
import base64
from datetime import datetime, timedelta
from sqlalchemy import func
import random
import string
import re
import json
import uuid
from create_lead_bitrix import create_lead, BitrixLeadError
from dotenv import load_dotenv

load_dotenv()

# Создаем таблицы в базе данных (если их еще нет)
Base.metadata.create_all(bind=engine)


def migrate_roles_schema():
    """Добавляет role и created_by_id, если их ещё нет (SQLite)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(sa_text('PRAGMA table_info(companies)'))]
        if 'role' not in cols:
            conn.execute(sa_text("ALTER TABLE companies ADD COLUMN role VARCHAR(20) DEFAULT 'partner'"))
            conn.execute(sa_text("UPDATE companies SET role = 'admin' WHERE is_admin = 1"))
            conn.execute(sa_text("UPDATE companies SET role = 'partner' WHERE is_admin = 0 OR is_admin IS NULL"))
        if 'created_by_id' not in cols:
            conn.execute(sa_text('ALTER TABLE companies ADD COLUMN created_by_id INTEGER'))


migrate_roles_schema()

# Инициализация Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or 'your-super-secret-key-change-in-production'  # Замени на случайную строку!
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB max upload
app.config['UPLOAD_VIDEO_FOLDER'] = os.path.join(app.root_path, 'static', 'video')
app.config['UPLOAD_IMG_FOLDER'] = os.path.join(app.root_path, 'static', 'img')
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'ogg'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

# Дефолтные пути (относительно static/)
DEFAULT_VIDEO_PATH = 'video/main_video.mp4'
DEFAULT_POSTER_PATH = 'img/video-poster.jpg'

# Тексты главной страницы (ключи SiteSetting + значения по умолчанию)
TEXT_DEFAULTS = {
    'page_title': 'E-CarsBurg - Продажа и доставка автомобилей',
    'hero_title': 'Приветствуем вас в E-CarsBurg!',
    'hero_subtitle': 'E-CarsBurg - ваш надежный партнер в мире автомобильных поставок! Мы специализируемся на индивидуальных заказах автомобилей из Китая, США, Южной Кореи и Европы, обеспечивая высочайший уровень сервиса и качества.',
    'promo_title': '🎁 Специальное предложение для вас',
    'promo_subtitle': 'Назовите этот промокод при обращении в E-CarsBurg и получите один из подарков на выбор:',
    'social_title': 'Мы в социальных сетях',
    'social_subtitle': 'Подписывайтесь на наши соц.сети и следите за новостями, обзорами и акциями',
    'gallery_title': 'Наши довольные покупатели',
    'gallery_subtitle': 'Люди которые доверили нам подобрать и доставить автомобили',
    'process_title': 'Как мы работаем',
    'process_subtitle': 'Прозрачный процесс от первого обращения до выдачи автомобиля',
    'footer_text': '© 2026 E-CarsBurg. Все права защищены.',
}


def get_site_texts(db):
    """Все тексты главной с подстановкой дефолтов"""
    texts = {}
    for key, default in TEXT_DEFAULTS.items():
        texts[key] = get_setting(db, f'text_{key}', default)
    return texts



def allowed_file(filename, allowed):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def get_setting(db, key, default=None):
    row = db.query(SiteSetting).filter(SiteSetting.key == key).first()
    return row.value if row and row.value else default


def set_setting(db, key, value):
    row = db.query(SiteSetting).filter(SiteSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(SiteSetting(key=key, value=value))
    db.commit()


def ensure_upload_dirs():
    os.makedirs(app.config['UPLOAD_VIDEO_FOLDER'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_IMG_FOLDER'], exist_ok=True)


def get_gallery_images(db):
    """Возвращает упорядоченный список имён изображений для карусели."""
    stored = get_setting(db, 'gallery_images', None)
    if stored is not None:
        try:
            names = json.loads(stored)
        except (TypeError, ValueError):
            names = []
        return [
            name for name in names
            if isinstance(name, str) and name == os.path.basename(name)
            and allowed_file(name, ALLOWED_IMAGE_EXTENSIONS)
            and os.path.isfile(os.path.join(app.config['UPLOAD_IMG_FOLDER'], name))
        ]

    # Совместимость с текущими фотографиями photo1.jpg, photo2.jpg и т.д.
    names = [
        name for name in os.listdir(app.config['UPLOAD_IMG_FOLDER'])
        if re.fullmatch(r'photo\d+\.(?:jpg|jpeg|png|webp)', name, re.IGNORECASE)
        and os.path.isfile(os.path.join(app.config['UPLOAD_IMG_FOLDER'], name))
    ]
    return sorted(names, key=lambda name: int(re.search(r'photo(\d+)', name, re.IGNORECASE).group(1)))

def save_gallery_images(db, names):
    """Сохраняет список имён файлов карусели в настройках сайта."""
    set_setting(db, 'gallery_images', json.dumps(names, ensure_ascii=False))


# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Куда редиректить, если пользователь не авторизован


def generate_password(length=12):
    """Генерирует случайный пароль"""
    chars = string.ascii_letters + string.digits + '!@#$%'
    return ''.join(random.choice(chars) for _ in range(length))


@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        # Стало (правильно для SQLAlchemy 2.0):
        return db.get(Company, int(user_id))
    finally:
        db.close()


# ==================== РОУТЫ ====================

@app.route('/')
def index():
    """Главная страница сайта-визитки"""
    db = SessionLocal()
    try:
        bonuses = db.query(Bonus).filter(Bonus.is_active == True).order_by(Bonus.sort_order.asc(), Bonus.id.asc()).all()
        video_path = get_setting(db, 'welcome_video', DEFAULT_VIDEO_PATH)
        poster_path = get_setting(db, 'welcome_poster', DEFAULT_POSTER_PATH)
        texts = get_site_texts(db)
        gallery_images = get_gallery_images(db)
        return render_template(
            'index.html',
            bonuses=bonuses,
            gallery_images=gallery_images,
            welcome_video=video_path,
            welcome_poster=poster_path,
            texts=texts
        )
    finally:
        db.close()


@app.route('/create-consultation-lead', methods=['POST'])
def create_consultation_lead():
    """Принимает заявку с формы консультации и создаёт лид в Bitrix24."""
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    name = ' '.join(str(data.get('name', '')).split())[:120]
    phone = ' '.join(str(data.get('phone', '')).split())[:40]
    promocode = ' '.join(str(data.get('promocode', '')).split())[:100] or 'ECARSBURG'
    consent = str(data.get('consent', '')).lower() in ('1', 'true', 'on', 'yes')

    if len(name) < 2:
        return jsonify(ok=False, message='Укажите ваше имя.'), 400
    if len(phone) < 6 or not re.search(r'\d', phone):
        return jsonify(ok=False, message='Укажите корректный номер телефона.'), 400
    if not consent:
        return jsonify(ok=False, message='Необходимо согласие на обработку персональных данных.'), 400

    try:
        result = create_lead(name=name, telephone_number=phone, promocode=promocode)
        app.logger.info('Bitrix24 lead created, id=%s', result.get('id'))
        return jsonify(ok=True, message='Спасибо! Заявка отправлена. Мы скоро свяжемся с вами.'), 200
    except BitrixLeadError as exc:
        app.logger.warning('Bitrix24 lead creation failed: %s', exc)
        return jsonify(ok=False, message='Не удалось отправить заявку. Попробуйте позже или свяжитесь с нами другим способом.'), 502
    except Exception:
        app.logger.exception('Unexpected error while creating Bitrix24 lead')
        return jsonify(ok=False, message='Произошла ошибка. Попробуйте позже.'), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа по названию компании (slug)"""
    if request.method == 'POST':
        slug = request.form.get('slug')  # Теперь это название компании
        password = request.form.get('password')

        db = SessionLocal()
        try:
            user = db.query(Company).filter(Company.slug == slug).first()

            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                flash(f'Вы успешно вошли: {user.role_label}', 'success')
                role = user.get_role()
                if role == ROLE_ADMIN:
                    return redirect(url_for('admin_dashboard'))
                if role == ROLE_SUPERVISOR:
                    return redirect(url_for('admin_companies'))
                return redirect(url_for('dashboard'))
            else:
                flash('Неверный логин или пароль', 'error')
        finally:
            db.close()

    return render_template('login.html')


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
        # Только партнёры имеют реферальные ссылки
        company = db.query(Company).filter(Company.slug == slug, Company.role == ROLE_PARTNER).first()
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

def admin_required(f):
    """Только главный администратор (полный доступ)"""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_main_admin:
            flash('Доступ запрещён. Только для главного администратора.', 'error')
            return redirect(url_for('post_login_redirect'))
        return f(*args, **kwargs)
    return decorated_function


def staff_required(f):
    """Админ или супервайзер (компании, пароли)"""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_staff:
            flash('Доступ запрещён.', 'error')
            return redirect(url_for('post_login_redirect'))
        return f(*args, **kwargs)
    return decorated_function


def partner_required(f):
    """Только партнёр (личный кабинет с QR и статистикой)"""
    from functools import wraps
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_partner:
            flash('Личный кабинет партнёра недоступен для вашей роли.', 'error')
            return redirect(url_for('post_login_redirect'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/home')
@login_required
def post_login_redirect():
    """Куда направить пользователя после входа в зависимости от роли"""
    role = current_user.get_role()
    if role == ROLE_ADMIN:
        return redirect(url_for('admin_dashboard'))
    if role == ROLE_SUPERVISOR:
        return redirect(url_for('admin_companies'))
    return redirect(url_for('dashboard'))



@app.route('/dashboard')
@partner_required
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

@app.route('/admin')
@admin_required
def admin_dashboard():
    """Главная страница админ-панели со статистикой"""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)

        # Компании (без админов)
        total_companies = db.query(Company).filter(Company.role == ROLE_PARTNER).count()

        # Клики (переходы)
        total_clicks = db.query(ClickEvent).count()
        clicks_today = db.query(ClickEvent).filter(ClickEvent.clicked_at >= today_start).count()
        clicks_week = db.query(ClickEvent).filter(ClickEvent.clicked_at >= week_ago).count()

        # Действия пользователей
        total_page_views = db.query(UserAction).filter(UserAction.action_type == 'page_view').count()
        total_social_clicks = db.query(UserAction).filter(UserAction.action_type == 'social_button_click').count()

        # Топ-5 компаний по кликам
        top_companies = db.query(
            Company.name,
            Company.slug,
            func.count(ClickEvent.id).label('total_clicks')
        ).outerjoin(ClickEvent, Company.id == ClickEvent.company_id) \
            .filter(Company.role == ROLE_PARTNER) \
            .group_by(Company.id, Company.name, Company.slug) \
            .order_by(func.count(ClickEvent.id).desc()) \
            .limit(5) \
            .all()

        # Последние 10 переходов
        recent_clicks = db.query(ClickEvent, Company) \
            .join(Company, ClickEvent.company_id == Company.id) \
            .order_by(ClickEvent.clicked_at.desc()) \
            .limit(10) \
            .all()

        return render_template(
            'admin_dashboard.html',
            total_companies=total_companies,
            total_clicks=total_clicks,
            clicks_today=clicks_today,
            clicks_week=clicks_week,
            total_page_views=total_page_views,
            total_social_clicks=total_social_clicks,
            top_companies=top_companies,
            recent_clicks=recent_clicks
        )
    finally:
        db.close()


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



@app.route('/admin/companies')
@staff_required
def admin_companies():
    """Управление компаниями"""
    db = SessionLocal()
    try:
        # Получаем только обычные компании (не админов)
        q = db.query(Company).filter(Company.role == ROLE_PARTNER)
        if current_user.is_supervisor:
            q = q.filter(Company.created_by_id == current_user.id)
        companies = q.order_by(Company.created_at.desc()).all()

        # Заранее собираем данные с количеством кликов
        companies_data = []
        for comp in companies:
            click_count = db.query(ClickEvent).filter_by(company_id=comp.id).count()
            companies_data.append({
                'company': comp,
                'clicks': click_count
            })

        return render_template('admin_companies.html', companies_data=companies_data)
    finally:
        db.close()


@app.route('/admin/companies/add', methods=['GET', 'POST'])
@staff_required
def admin_add_company():
    """Добавление новой компании"""
    if request.method == 'POST':
        name = request.form.get('name')
        slug = request.form.get('slug')

        db = SessionLocal()
        try:
            # Проверка уникальности slug
            if db.query(Company).filter(Company.slug == slug).first():
                flash('Это название уже занято. Придумайте другое.', 'error')
                return redirect(url_for('admin_add_company'))

            # Генерация пароля
            password = generate_password(12)

            # Создание компании
            new_company = Company(
                name=name,
                slug=slug,
                email=f"{slug}@ecarsburg.local",
                password_hash=generate_password_hash(password),
                is_admin=False,
                role=ROLE_PARTNER,
                created_by_id=current_user.id,
            )
            db.add(new_company)
            db.commit()

            flash(f'Компания создана успешно! Логин: {slug}, Пароль: {password}', 'success')
            return redirect(url_for('admin_companies'))
        except Exception as e:
            db.rollback()
            flash(f'Ошибка при создании компании: {str(e)}', 'error')
        finally:
            db.close()

    return render_template('admin_add_company.html')


@app.route('/admin/companies/delete/<int:company_id>', methods=['POST'])
@admin_required
def admin_delete_company(company_id):
    """Удаление компании"""
    db = SessionLocal()
    try:
        company = db.query(Company).get(company_id)
        if company and company.is_partner:
            db.delete(company)
            db.commit()
            flash(f'Компания "{company.name}" удалена', 'success')
        else:
            flash('Не удалось удалить компанию', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Ошибка при удалении: {str(e)}', 'error')
    finally:
        db.close()

    return redirect(url_for('admin_companies'))


@app.route('/admin/companies/<int:company_id>/change-password', methods=['GET', 'POST'])
@staff_required
def admin_change_password(company_id):
    """Смена пароля компании"""
    db = SessionLocal()
    try:
        company = db.query(Company).get(company_id)
        if not company or not company.is_partner:
            flash('Компания не найдена или это не партнёр', 'error')
            return redirect(url_for('admin_companies'))

        if request.method == 'POST':
            # Генерируем новый пароль
            new_password = generate_password(12)

            # Обновляем пароль в базе
            company.password_hash = generate_password_hash(new_password)
            db.commit()

            flash(f'Пароль успешно изменен! Новый пароль: {new_password}', 'success')
            return redirect(url_for('admin_companies'))

        return render_template('admin_change_password.html', company=company)
    finally:
        db.close()

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



# ==================== УПРАВЛЕНИЕ БОНУСАМИ ====================

DEFAULT_BONUSES = [
    {'icon': '🛡️', 'title': '1 год гарантии', 'description': 'Расширенная гарантия на купленный автомобиль', 'sort_order': 1},
    {'icon': '✨', 'title': 'Детейлинг', 'description': 'Профессиональная химчистка и полировка кузова', 'sort_order': 2},
    {'icon': '❄️', 'title': 'Зимние шины', 'description': 'Комплект качественной зимней резины в подарок', 'sort_order': 3},
]


def ensure_default_bonuses(db):
    """Создаёт стартовые бонусы, если таблица пуста"""
    if db.query(Bonus).count() == 0:
        for item in DEFAULT_BONUSES:
            db.add(Bonus(**item, is_active=True))
        db.commit()


@app.route('/admin/bonuses')
@admin_required
def admin_bonuses():
    """Список бонусов (подарков за промокод)"""
    db = SessionLocal()
    try:
        ensure_default_bonuses(db)
        bonuses = db.query(Bonus).order_by(Bonus.sort_order.asc(), Bonus.id.asc()).all()
        return render_template('admin_bonuses.html', bonuses=bonuses)
    finally:
        db.close()


@app.route('/admin/bonuses/add', methods=['GET', 'POST'])
@admin_required
def admin_add_bonus():
    """Добавление бонуса"""
    if request.method == 'POST':
        icon = (request.form.get('icon') or '🎁').strip()[:20]
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        sort_order = request.form.get('sort_order', type=int) or 0
        is_active = request.form.get('is_active') == 'on'

        if not title:
            flash('Укажите название бонуса', 'error')
            return redirect(url_for('admin_add_bonus'))

        db = SessionLocal()
        try:
            bonus = Bonus(
                icon=icon or '🎁',
                title=title,
                description=description or None,
                sort_order=sort_order,
                is_active=is_active
            )
            db.add(bonus)
            db.commit()
            flash(f'Бонус «{title}» добавлен', 'success')
            return redirect(url_for('admin_bonuses'))
        except Exception as e:
            db.rollback()
            flash(f'Ошибка: {str(e)}', 'error')
        finally:
            db.close()

    return render_template('admin_bonus_form.html', bonus=None, form_action=url_for('admin_add_bonus'), page_title='Добавить бонус')


@app.route('/admin/bonuses/edit/<int:bonus_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_bonus(bonus_id):
    """Редактирование бонуса"""
    db = SessionLocal()
    try:
        bonus = db.query(Bonus).get(bonus_id)
        if not bonus:
            flash('Бонус не найден', 'error')
            return redirect(url_for('admin_bonuses'))

        if request.method == 'POST':
            title = (request.form.get('title') or '').strip()
            if not title:
                flash('Укажите название бонуса', 'error')
                return redirect(url_for('admin_edit_bonus', bonus_id=bonus_id))

            bonus.icon = (request.form.get('icon') or '🎁').strip()[:20] or '🎁'
            bonus.title = title
            bonus.description = (request.form.get('description') or '').strip() or None
            bonus.sort_order = request.form.get('sort_order', type=int) or 0
            bonus.is_active = request.form.get('is_active') == 'on'
            db.commit()
            flash(f'Бонус «{bonus.title}» обновлён', 'success')
            return redirect(url_for('admin_bonuses'))

        return render_template(
            'admin_bonus_form.html',
            bonus=bonus,
            form_action=url_for('admin_edit_bonus', bonus_id=bonus.id),
            page_title='Редактировать бонус'
        )
    finally:
        db.close()


@app.route('/admin/bonuses/delete/<int:bonus_id>', methods=['POST'])
@admin_required
def admin_delete_bonus(bonus_id):
    """Удаление бонуса"""
    db = SessionLocal()
    try:
        bonus = db.query(Bonus).get(bonus_id)
        if bonus:
            title = bonus.title
            db.delete(bonus)
            db.commit()
            flash(f'Бонус «{title}» удалён', 'success')
        else:
            flash('Бонус не найден', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Ошибка при удалении: {str(e)}', 'error')
    finally:
        db.close()
    return redirect(url_for('admin_bonuses'))


@app.route('/admin/bonuses/toggle/<int:bonus_id>', methods=['POST'])
@admin_required
def admin_toggle_bonus(bonus_id):
    """Включить / выключить отображение бонуса"""
    db = SessionLocal()
    try:
        bonus = db.query(Bonus).get(bonus_id)
        if bonus:
            bonus.is_active = not bonus.is_active
            db.commit()
            status = 'включён' if bonus.is_active else 'выключен'
            flash(f'Бонус «{bonus.title}» {status}', 'success')
        else:
            flash('Бонус не найден', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
    finally:
        db.close()
    return redirect(url_for('admin_bonuses'))


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


# ==================== МЕДИА / ВИДЕО ====================

@app.route('/admin/media', methods=['GET', 'POST'])
@admin_required
def admin_media():
    """Загрузка и смена видео/постера на главной"""
    ensure_upload_dirs()
    db = SessionLocal()
    try:
        current_video = get_setting(db, 'welcome_video', DEFAULT_VIDEO_PATH)
        current_poster = get_setting(db, 'welcome_poster', DEFAULT_POSTER_PATH)

        if request.method == 'POST':
            action = request.form.get('action', 'upload')

            if action == 'reset_video':
                set_setting(db, 'welcome_video', DEFAULT_VIDEO_PATH)
                flash('Видео сброшено на значение по умолчанию', 'success')
                return redirect(url_for('admin_media'))

            if action == 'reset_poster':
                set_setting(db, 'welcome_poster', DEFAULT_POSTER_PATH)
                flash('Постер сброшен на значение по умолчанию', 'success')
                return redirect(url_for('admin_media'))

            # Загрузка видео
            video_file = request.files.get('video')
            if video_file and video_file.filename:
                if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
                    flash('Допустимые форматы видео: mp4, webm, ogg', 'error')
                    return redirect(url_for('admin_media'))

                ext = video_file.filename.rsplit('.', 1)[1].lower()
                safe_name = f"welcome_video.{ext}"
                save_path = os.path.join(app.config['UPLOAD_VIDEO_FOLDER'], safe_name)
                video_file.save(save_path)
                set_setting(db, 'welcome_video', f'video/{safe_name}')
                flash('Видео успешно обновлено', 'success')

            # Загрузка постера
            poster_file = request.files.get('poster')
            if poster_file and poster_file.filename:
                if not allowed_file(poster_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                    flash('Допустимые форматы постера: jpg, jpeg, png, webp', 'error')
                    return redirect(url_for('admin_media'))

                ext = poster_file.filename.rsplit('.', 1)[1].lower()
                safe_name = f"video-poster.{ext}"
                save_path = os.path.join(app.config['UPLOAD_IMG_FOLDER'], safe_name)
                poster_file.save(save_path)
                set_setting(db, 'welcome_poster', f'img/{safe_name}')
                flash('Постер успешно обновлён', 'success')

            if not (video_file and video_file.filename) and not (poster_file and poster_file.filename):
                if action == 'upload':
                    flash('Выберите файл видео или постера', 'error')

            return redirect(url_for('admin_media'))

        return render_template(
            'admin_media.html',
            current_video=current_video,
            current_poster=current_poster,
            default_video=DEFAULT_VIDEO_PATH,
            default_poster=DEFAULT_POSTER_PATH
        )
    finally:
        db.close()




# ==================== СУПЕРВАЙЗЕРЫ (только главный админ) ====================

@app.route('/admin/gallery', methods=['GET', 'POST'])
@admin_required
def admin_gallery():
    """Главный администратор управляет фотографиями карусели на главной."""
    ensure_upload_dirs()
    db = SessionLocal()
    try:
        images = get_gallery_images(db)

        if request.method == 'POST':
            action = request.form.get('action', 'upload')

            if action == 'delete':
                filename = request.form.get('filename', '')
                # Удаляем только файл, который действительно присутствует в карусели.
                if filename not in images or filename != os.path.basename(filename):
                    flash('Фотография не найдена в карусели.', 'error')
                    return redirect(url_for('admin_gallery'))
                path = os.path.join(app.config['UPLOAD_IMG_FOLDER'], filename)
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    images.remove(filename)
                    save_gallery_images(db, images)
                    flash('Фотография удалена из карусели.', 'success')
                except OSError:
                    app.logger.exception('Could not delete gallery image %s', filename)
                    flash('Не удалось удалить файл фотографии.', 'error')
                return redirect(url_for('admin_gallery'))

            uploaded = request.files.getlist('images')
            valid_uploads = [file for file in uploaded if file and file.filename]
            if not valid_uploads:
                flash('Выберите одну или несколько фотографий для загрузки.', 'error')
                return redirect(url_for('admin_gallery'))

            saved = []
            for image_file in valid_uploads:
                if not allowed_file(image_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                    flash(f'Недопустимый формат файла: {image_file.filename}. Используйте JPG, JPEG, PNG или WEBP.', 'error')
                    continue
                ext = image_file.filename.rsplit('.', 1)[1].lower()
                filename = f'gallery_{uuid.uuid4().hex}.{ext}'
                destination = os.path.join(app.config['UPLOAD_IMG_FOLDER'], filename)
                try:
                    image_file.save(destination)
                    saved.append(filename)
                except OSError:
                    app.logger.exception('Could not save gallery image')
                    flash('Не удалось сохранить одну из фотографий.', 'error')

            if saved:
                images.extend(saved)
                save_gallery_images(db, images)
                flash(f'Загружено фотографий: {len(saved)}.', 'success')
            elif valid_uploads:
                flash('Фотографии не были загружены. Проверьте формат файлов.', 'error')
            return redirect(url_for('admin_gallery'))

        return render_template('admin_gallery.html', images=images)
    finally:
        db.close()


@app.route('/admin/supervisors')
@admin_required
def admin_supervisors():
    """Список супервайзеров и статистика их работы"""
    db = SessionLocal()
    try:
        supervisors = db.query(Company).filter(Company.role == ROLE_SUPERVISOR).order_by(Company.created_at.desc()).all()
        stats = []
        for s in supervisors:
            created_companies = db.query(Company).filter(
                Company.created_by_id == s.id,
                Company.role == ROLE_PARTNER
            ).all()
            company_ids = [c.id for c in created_companies]
            total_clicks = 0
            if company_ids:
                total_clicks = db.query(func.count(ClickEvent.id)).filter(
                    ClickEvent.company_id.in_(company_ids)
                ).scalar() or 0
            stats.append({
                'supervisor': s,
                'companies_count': len(created_companies),
                'companies': created_companies,
                'total_clicks': total_clicks,
            })
        return render_template('admin_supervisors.html', stats=stats, active_nav='supervisors')
    finally:
        db.close()


@app.route('/admin/supervisors/add', methods=['GET', 'POST'])
@admin_required
def admin_add_supervisor():
    """Создание аккаунта супервайзера"""
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        slug = (request.form.get('slug') or '').strip().lower()
        password = (request.form.get('password') or '').strip()

        if not name or not slug:
            flash('Укажите имя и логин', 'error')
            return redirect(url_for('admin_add_supervisor'))

        db = SessionLocal()
        try:
            if db.query(Company).filter(Company.slug == slug).first():
                flash('Такой логин уже занят', 'error')
                return redirect(url_for('admin_add_supervisor'))

            if not password:
                password = generate_password(12)

            sup = Company(
                name=name,
                slug=slug,
                email=f"{slug}@supervisor.ecarsburg.local",
                password_hash=generate_password_hash(password),
                is_admin=False,
                role=ROLE_SUPERVISOR,
                created_by_id=current_user.id,
            )
            db.add(sup)
            db.commit()
            flash(f'Супервайзер создан. Логин: {slug}, Пароль: {password}', 'success')
            return redirect(url_for('admin_supervisors'))
        except Exception as e:
            db.rollback()
            flash(f'Ошибка: {e}', 'error')
        finally:
            db.close()

    return render_template('admin_add_supervisor.html', active_nav='supervisors')


@app.route('/admin/supervisors/<int:sup_id>/change-password', methods=['GET', 'POST'])
@admin_required
def admin_supervisor_password(sup_id):
    db = SessionLocal()
    try:
        sup = db.query(Company).get(sup_id)
        if not sup or not sup.is_supervisor:
            flash('Супервайзер не найден', 'error')
            return redirect(url_for('admin_supervisors'))

        if request.method == 'POST':
            password = (request.form.get('password') or '').strip()
            if not password:
                password = generate_password(12)
            sup.password_hash = generate_password_hash(password)
            db.commit()
            flash(f'Новый пароль для {sup.slug}: {password}', 'success')
            return redirect(url_for('admin_supervisors'))

        return render_template('admin_change_password.html', company=sup, active_nav='supervisors')
    finally:
        db.close()


@app.route('/admin/supervisors/delete/<int:sup_id>', methods=['POST'])
@admin_required
def admin_delete_supervisor(sup_id):
    db = SessionLocal()
    try:
        sup = db.query(Company).get(sup_id)
        if sup and sup.is_supervisor:
            db.delete(sup)
            db.commit()
            flash(f'Супервайзер «{sup.name}» удалён', 'success')
        else:
            flash('Не удалось удалить', 'error')
    except Exception as e:
        db.rollback()
        flash(f'Ошибка: {e}', 'error')
    finally:
        db.close()
    return redirect(url_for('admin_supervisors'))


# ==================== ТЕКСТЫ ГЛАВНОЙ ====================

@app.route('/admin/texts', methods=['GET', 'POST'])
@admin_required
def admin_texts():
    """Редактирование текстов главной страницы"""
    db = SessionLocal()
    try:
        if request.method == 'POST':
            action = request.form.get('action', 'save')
            if action == 'reset':
                for key in TEXT_DEFAULTS:
                    set_setting(db, f'text_{key}', TEXT_DEFAULTS[key])
                flash('Все тексты сброшены к значениям по умолчанию', 'success')
                return redirect(url_for('admin_texts'))

            for key in TEXT_DEFAULTS:
                value = (request.form.get(key) or '').strip()
                if not value:
                    value = TEXT_DEFAULTS[key]
                set_setting(db, f'text_{key}', value)
            flash('Тексты главной страницы сохранены', 'success')
            return redirect(url_for('admin_texts'))

        texts = get_site_texts(db)
        return render_template('admin_texts.html', texts=texts, defaults=TEXT_DEFAULTS)
    finally:
        db.close()


# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG') == '1')