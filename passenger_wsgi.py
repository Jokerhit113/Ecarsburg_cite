# Точка входа для Passenger (виртуальный хостинг Beget).
# Файл должен лежать в корне сайта, рядом с app.py.
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from app import app as application  # Passenger ищет объект с именем "application"
