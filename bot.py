import requests
import time
import sqlite3
from datetime import datetime, timedelta
import logging
import threading

class NightModeBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.setup_database()
        self.setup_logging()
        self.user_states = {}
        self.user_current_chat = {}
        
        # Запускаем фоновую проверку времени
        self.background_thread = threading.Thread(target=self.background_time_check, daemon=True)
        self.background_thread.start()
        
        print("🤖 Бот-модератор ночного режима запущен!")
        print("⏰ Фоновая проверка времени активирована")
        print("💾 Сообщения сохраняются и удаляются в конце периода")
        print("📱 Напишите /start в Telegram")

    def setup_database(self):
        """Настройка базы данных с проверкой существующих колонок"""
        self.conn = sqlite3.connect('night_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Создаем таблицу настроек чатов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT,
                night_mode_enabled INTEGER DEFAULT 0,
                start_time TEXT DEFAULT '23:00',
                end_time TEXT DEFAULT '05:00',
                welcome_message TEXT DEFAULT '🌙 Ночной режим активирован! Сообщения будут удаляться в конце периода.',
                is_active INTEGER DEFAULT 1,
                added_date TEXT,
                last_notification_date TEXT,
                is_night_mode_active INTEGER DEFAULT 0
            )
        ''')
        
        # Добавляем недостающие колонки если их нет
        try:
            self.cursor.execute("ALTER TABLE chat_settings ADD COLUMN last_notification_date TEXT")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
            
        try:
            self.cursor.execute("ALTER TABLE chat_settings ADD COLUMN is_night_mode_active INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
        
        # Сохраненные сообщения для удаления
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                user_id INTEGER,
                message_text TEXT,
                message_type TEXT DEFAULT 'text',
                saved_date TEXT,
                night_mode_session TEXT,
                FOREIGN KEY (chat_id) REFERENCES chat_settings (chat_id)
            )
        ''')
        
        # Добавляем колонку message_type если её нет
        try:
            self.cursor.execute("ALTER TABLE saved_messages ADD COLUMN message_type TEXT DEFAULT 'text'")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует
        
        # Сессии ночного режима
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS night_sessions (
                session_id TEXT PRIMARY KEY,
                chat_id INTEGER,
                start_time TEXT,
                end_time TEXT,
                message_count INTEGER DEFAULT 0,
                is_completed INTEGER DEFAULT 0
            )
        ''')
        
        self.conn.commit()

    def setup_logging(self):
        """Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('night_bot.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger()

    def send_message(self, chat_id, text, reply_markup=None):
        """Отправить сообщение"""
        url = self.base_url + "sendMessage"
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            params["reply_markup"] = reply_markup
            
        try:
            response = requests.post(url, json=params, timeout=10)
            if response.json().get("ok"):
                self.logger.info(f"✅ Сообщение отправлено в {chat_id}")
                return True
            else:
                self.logger.error(f"❌ Ошибка отправки в {chat_id}: {response.json()}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def delete_message(self, chat_id, message_id):
        """Удалить сообщение"""
        url = self.base_url + "deleteMessage"
        params = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        
        try:
            response = requests.post(url, json=params, timeout=10)
            if response.json().get("ok"):
                self.logger.info(f"🗑️ Сообщение {message_id} удалено в {chat_id}")
                return True
            else:
                error = response.json().get('description', 'Unknown error')
                self.logger.warning(f"⚠️ Не удалось удалить сообщение в {chat_id}: {error}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Ошибка удаления: {e}")
            return False

    def create_keyboard(self, buttons, rows=1):
        """Создать клавиатуру"""
        keyboard = []
        row = []
        
        for i, button in enumerate(buttons):
            row.append({"text": button})
            if (i + 1) % rows == 0:
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
            
        return {"keyboard": keyboard, "resize_keyboard": True}

    def create_inline_keyboard(self, buttons):
        """Создать инлайн клавиатуру"""
        keyboard = []
        
        for button_row in buttons:
            row = []
            for button_text, callback_data in button_row:
                row.append({"text": button_text, "callback_data": callback_data})
            keyboard.append(row)
            
        return {"inline_keyboard": keyboard}

    def get_message_type(self, message):
        """Определить тип сообщения"""
        if "text" in message:
            return "text"
        elif "sticker" in message:
            return "sticker"
        elif "photo" in message:
            return "photo"
        elif "video" in message:
            return "video"
        elif "document" in message:
            return "document"
        elif "audio" in message:
            return "audio"
        elif "voice" in message:
            return "voice"
        elif "video_note" in message:
            return "video_note"
        elif "animation" in message:
            return "animation"
        elif "location" in message:
            return "location"
        elif "contact" in message:
            return "contact"
        else:
            return "unknown"

    def get_message_content(self, message):
        """Получить текстовое представление сообщения"""
        message_type = self.get_message_type(message)
        
        if message_type == "text":
            return message.get("text", "")
        elif message_type == "sticker":
            emoji = message["sticker"].get("emoji", "")
            return f"Стикер {emoji}"
        elif message_type == "photo":
            caption = message.get("caption", "")
            return f"Фото {caption}".strip()
        elif message_type == "video":
            caption = message.get("caption", "")
            return f"Видео {caption}".strip()
        elif message_type == "document":
            caption = message.get("caption", "")
            file_name = message["document"].get("file_name", "")
            return f"Документ {file_name} {caption}".strip()
        elif message_type == "audio":
            caption = message.get("caption", "")
            title = message["audio"].get("title", "")
            return f"Аудио {title} {caption}".strip()
        elif message_type == "voice":
            return "Голосовое сообщение"
        elif message_type == "video_note":
            return "Кружочек видео"
        elif message_type == "animation":
            caption = message.get("caption", "")
            return f"GIF {caption}".strip()
        elif message_type == "location":
            lat = message["location"]["latitude"]
            lon = message["location"]["longitude"]
            return f"📍 Локация ({lat}, {lon})"
        elif message_type == "contact":
            contact = message["contact"]
            name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
            phone = contact.get("phone_number", "")
            return f"👤 Контакт {name} {phone}".strip()
        else:
            return "Медиа-сообщение"

    def background_time_check(self):
        """Фоновая проверка времени для ночного режима"""
        self.logger.info("⏰ Запущена фоновая проверка времени")
        
        while True:
            try:
                current_time = datetime.now().strftime("%H:%M")
                current_date = datetime.now().strftime("%Y-%m-%d")
                
                # Получаем все активные чаты с включенным ночным режимом
                self.cursor.execute('''
                    SELECT chat_id, start_time, end_time, welcome_message, last_notification_date, is_night_mode_active 
                    FROM chat_settings 
                    WHERE night_mode_enabled = 1 AND is_active = 1
                ''')
                chats = self.cursor.fetchall()
                
                for chat_id, start_time, end_time, welcome_message, last_notification, is_night_active in chats:
                    
                    # Проверяем, наступило ли время начала ночного режима
                    if current_time == start_time and not is_night_active:
                        # Начало ночного режима
                        session_id = f"{chat_id}_{datetime.now().strftime('%Y%m%d_%H%M')}"
                        
                        # Создаем новую сессию
                        self.cursor.execute('''
                            INSERT OR REPLACE INTO night_sessions 
                            (session_id, chat_id, start_time, end_time) 
                            VALUES (?, ?, ?, ?)
                        ''', (session_id, chat_id, datetime.now().isoformat(), end_time))
                        
                        # Активируем ночной режим
                        self.cursor.execute(
                            'UPDATE chat_settings SET is_night_mode_active = 1, last_notification_date = ? WHERE chat_id = ?',
                            (current_date, chat_id)
                        )
                        
                        # Отправляем уведомление
                        self.send_message(chat_id, welcome_message)
                        self.logger.info(f"🌙 Ночной режим начался в чате {chat_id}, сессия: {session_id}")
                        
                        self.conn.commit()
                    
                    # Проверяем, наступило ли время окончания ночного режима
                    elif current_time == end_time and is_night_active:
                        # Завершение ночного режима - удаляем все сохраненные сообщения
                        self.end_night_mode(chat_id)
                        
                time.sleep(60)  # Проверяем каждую минуту
                
            except Exception as e:
                self.logger.error(f"❌ Ошибка в фоновой проверке: {e}")
                time.sleep(60)

    def end_night_mode(self, chat_id):
        """Завершить ночной режим и удалить все сообщения"""
        try:
            # Получаем текущую активную сессию
            self.cursor.execute('''
                SELECT session_id FROM night_sessions 
                WHERE chat_id = ? AND is_completed = 0 
                ORDER BY start_time DESC LIMIT 1
            ''', (chat_id,))
            session = self.cursor.fetchone()
            
            if session:
                session_id = session[0]
                
                # Получаем все сообщения для этой сессии
                self.cursor.execute('''
                    SELECT message_id FROM saved_messages 
                    WHERE chat_id = ? AND night_mode_session = ?
                ''', (chat_id, session_id))
                
                messages = self.cursor.fetchall()
                deleted_count = 0
                
                # Удаляем все сообщения
                for message_row in messages:
                    message_id = message_row[0]
                    if self.delete_message(chat_id, message_id):
                        deleted_count += 1
                    time.sleep(0.1)  # Небольшая задержка между удалениями
                
                # Отправляем отчет
                settings = self.get_chat_settings(chat_id)
                if settings:
                    start_time = settings[3] if len(settings) > 3 else "23:00"
                    end_time = settings[4] if len(settings) > 4 else "05:00"
                    
                    report_text = f"""
☀️ <b>Ночной режим завершен</b>

Удалено сообщений: {deleted_count}
Период: с {start_time} до {end_time}

💬 Сообщения за ночной период очищены.
"""
                    self.send_message(chat_id, report_text)
                
                # Помечаем сессию как завершенную
                self.cursor.execute(
                    'UPDATE night_sessions SET is_completed = 1, message_count = ? WHERE session_id = ?',
                    (deleted_count, session_id)
                )
                
                # Деактивируем ночной режим
                self.cursor.execute(
                    'UPDATE chat_settings SET is_night_mode_active = 0 WHERE chat_id = ?',
                    (chat_id,)
                )
                
                self.conn.commit()
                self.logger.info(f"☀️ Ночной режим завершен в чате {chat_id}, удалено {deleted_count} сообщений")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка завершения ночного режима: {e}")

    def save_message(self, chat_id, message_id, user_id, message_text, message_type, session_id):
        """Сохранить сообщение для последующего удаления"""
        try:
            self.cursor.execute('''
                INSERT INTO saved_messages 
                (chat_id, message_id, user_id, message_text, message_type, saved_date, night_mode_session) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, message_id, user_id, message_text[:500], message_type, datetime.now().isoformat(), session_id))
            self.conn.commit()
            self.logger.info(f"💾 Сообщение {message_id} ({message_type}) сохранено для удаления в сессии {session_id}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения сообщения: {e}")

    def get_current_session(self, chat_id):
        """Получить текущую активную сессию ночного режима"""
        self.cursor.execute('''
            SELECT session_id FROM night_sessions 
            WHERE chat_id = ? AND is_completed = 0 
            ORDER BY start_time DESC LIMIT 1
        ''', (chat_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def handle_message(self, message_obj, user_id, chat_id):
        """Обработка сообщений"""
        message_type = self.get_message_type(message_obj)
        message_content = self.get_message_content(message_obj)
        
        self.logger.info(f"📨 Сообщение от {user_id} в {chat_id}: [{message_type}] {message_content}")
        
        # Для личных сообщений с ботом - обрабатываем только текстовые команды
        if chat_id > 0:
            if message_type == "text":
                return self.handle_private_message(message_content, user_id, chat_id)
            else:
                # В личных сообщениях игнорируем не-текстовые сообщения
                return True
        else:
            return self.handle_group_message(message_content, user_id, chat_id, message_obj, message_type)

    def handle_private_message(self, message_text, user_id, chat_id):
        """Обработка личных сообщений"""
        
        # Обработка состояний в первую очередь
        if user_id in self.user_states:
            state = self.user_states[user_id]
            
            if state.startswith("waiting_time_"):
                target_chat_id = self.user_current_chat.get(user_id)
                if target_chat_id:
                    if self.is_valid_time(message_text):
                        if "start" in state:
                            self.update_start_time(target_chat_id, message_text)
                            self.send_message(chat_id, f"✅ Время начала установлено: {message_text}")
                        else:
                            self.update_end_time(target_chat_id, message_text)
                            self.send_message(chat_id, f"✅ Время окончания установлено: {message_text}")
                        del self.user_states[user_id]
                        self.show_chat_settings(chat_id, target_chat_id, user_id)
                    else:
                        self.send_message(chat_id, "❌ Неверный формат времени. Используйте ЧЧ:MM (например, 23:00)")
                return True
                
            elif state == "waiting_message":
                target_chat_id = self.user_current_chat.get(user_id)
                if target_chat_id:
                    self.update_welcome_message(target_chat_id, message_text)
                    del self.user_states[user_id]
                    self.send_message(chat_id, "✅ Сообщение обновлено!")
                    self.show_chat_settings(chat_id, target_chat_id, user_id)
                return True
                
            elif state == "waiting_chat_id":
                try:
                    target_chat_id = int(message_text)
                    # Создаем или обновляем запись
                    self.cursor.execute('''
                        INSERT OR REPLACE INTO chat_settings 
                        (chat_id, is_active, added_date) 
                        VALUES (?, 1, ?)
                    ''', (target_chat_id, datetime.now().isoformat()))
                    self.conn.commit()
                    del self.user_states[user_id]
                    self.user_current_chat[user_id] = target_chat_id
                    self.send_message(chat_id, f"✅ Чат {target_chat_id} добавлен!")
                    self.show_chat_settings(chat_id, target_chat_id, user_id)
                except ValueError:
                    self.send_message(chat_id, "❌ Неверный формат ID. Введите числовой ID чата.")
                return True

        # Обработка команд
        if message_text == "/start":
            self.show_main_menu(chat_id)
            return True
            
        elif message_text == "🔙 Главное меню":
            self.show_main_menu(chat_id)
            return True
            
        elif message_text == "📋 Мои чаты":
            self.show_my_chats(user_id, chat_id)
            return True
            
        elif message_text == "➕ Добавить чат":
            self.user_states[user_id] = "waiting_chat_id"
            self.send_message(chat_id, 
                "📝 Введите ID чата для добавления:\n\n"
                "Чтобы получить ID чата, добавьте бота в группу и напишите в ней команду /id")
            return True
            
        elif message_text == "❓ Помощь":
            self.show_help(chat_id)
            return True
            
        else:
            self.show_main_menu(chat_id)
            return True

    def handle_callback(self, callback_data, user_id, chat_id, message_id):
        """Обработка callback от инлайн кнопок"""
        print(f"🔧 Callback: {callback_data} от пользователя {user_id}")
        
        if callback_data == "main_menu":
            self.show_main_menu(chat_id)
            
        elif callback_data.startswith("select_chat_"):
            chat_id_str = callback_data[12:]
            try:
                target_chat_id = int(chat_id_str)
                self.user_current_chat[user_id] = target_chat_id
                self.show_chat_settings(chat_id, target_chat_id, user_id)
            except ValueError:
                self.send_message(chat_id, "❌ Ошибка выбора чата")
                
        elif callback_data.startswith("toggle_mode_"):
            chat_id_str = callback_data[12:]
            try:
                target_chat_id = int(chat_id_str)
                settings = self.get_chat_settings(target_chat_id)
                if settings:
                    if settings[2]:  # Если включен
                        self.disable_night_mode(target_chat_id)
                        self.send_message(chat_id, "✅ Ночной режим выключен")
                    else:
                        self.enable_night_mode(target_chat_id)
                        self.send_message(chat_id, "✅ Ночной режим включен")
                    self.show_chat_settings(chat_id, target_chat_id, user_id)
            except ValueError:
                self.send_message(chat_id, "❌ Ошибка переключения режима")
                
        elif callback_data.startswith("edit_start_"):
            chat_id_str = callback_data[11:]
            try:
                target_chat_id = int(chat_id_str)
                self.user_current_chat[user_id] = target_chat_id
                self.user_states[user_id] = "waiting_time_start"
                self.send_message(chat_id, 
                    "⏰ Введите время начала ночного режима:\n\n"
                    "Формат: ЧЧ:MM (24-часовой)\n"
                    "Пример: 23:00 или 22:30\n\n"
                    "В это время бот отправит сообщение и начнет сохранять сообщения.")
            except ValueError:
                self.send_message(chat_id, "❌ Ошибка настройки времени")
                
        elif callback_data.startswith("edit_end_"):
            chat_id_str = callback_data[9:]
            try:
                target_chat_id = int(chat_id_str)
                self.user_current_chat[user_id] = target_chat_id
                self.user_states[user_id] = "waiting_time_end"
                self.send_message(chat_id, 
                    "⏰ Введите время окончания ночного режима:\n\n"
                    "Формат: ЧЧ:MM (24-часовой)\n"
                    "Пример: 05:00 или 06:30\n\n"
                    "В это время бот удалит все сохраненные сообщения.")
            except ValueError:
                self.send_message(chat_id, "❌ Ошибка настройки времени")
                
        elif callback_data.startswith("edit_message_"):
            chat_id_str = callback_data[13:]
            try:
                target_chat_id = int(chat_id_str)
                self.user_current_chat[user_id] = target_chat_id
                self.user_states[user_id] = "waiting_message"
                self.send_message(chat_id, 
                    "📝 Введите приветственное сообщение:\n\n"
                    "Это сообщение будет отправляться при начале ночного режима.\n"
                    "Пример: 🌙 Ночной режим активирован! Сообщения будут сохраняться и удаляться в 5:00.")
            except ValueError:
                self.send_message(chat_id, "❌ Ошибка настройки сообщения")

        # Ответ на callback (убирает часики)
        try:
            requests.post(f"{self.base_url}answerCallbackQuery", 
                         json={"callback_query_id": callback_data})
        except:
            pass

    def handle_group_message(self, message_text, user_id, chat_id, message_obj, message_type):
        """Обработка сообщений в группе"""
        if message_type == "text":
            if message_text == "/id":
                self.send_message(chat_id, f"🆔 ID этого чата: <code>{chat_id}</code>\n\nСкопируйте этот ID для настройки в личном чате с ботом.")
                return True
                
            elif message_text == "/start":
                self.show_group_help(chat_id)
                return True
                
            elif message_text == "/status":
                self.show_group_status(chat_id)
                return True
                
            elif message_text == "/test_night":
                # Тестовая команда для проверки ночного режима
                settings = self.get_chat_settings(chat_id)
                if settings and len(settings) > 2 and settings[2]:
                    current_session = self.get_current_session(chat_id)
                    if current_session:
                        # Считаем сохраненные сообщения
                        self.cursor.execute('SELECT COUNT(*) FROM saved_messages WHERE chat_id = ? AND night_mode_session = ?', 
                                          (chat_id, current_session))
                        saved_count = self.cursor.fetchone()[0]
                        
                        end_time = settings[4] if len(settings) > 4 else "05:00"
                        self.send_message(chat_id, 
                            f"🔴 ТЕСТ: Ночной режим АКТИВЕН\n"
                            f"💾 Сообщений сохранено: {saved_count}\n"
                            f"⏰ Удаление в: {end_time}")
                    else:
                        self.send_message(chat_id, "🟢 ТЕСТ: Ночной режим НЕАКТИВЕН (ожидание начала)")
                else:
                    self.send_message(chat_id, "🟢 ТЕСТ: Ночной режим ВЫКЛЮЧЕН")
                return True
                
            elif message_text == "/force_cleanup" and self.is_user_admin(chat_id, user_id):
                # Принудительная очистка (только для админов)
                self.end_night_mode(chat_id)
                return True

        # Сохраняем сообщение если ночной режим активен
        settings = self.get_chat_settings(chat_id)
        if settings and len(settings) > 9 and settings[9]:  # is_night_mode_active
            current_session = self.get_current_session(chat_id)
            if current_session:
                self.save_message(chat_id, message_obj["message_id"], user_id, message_text, message_type, current_session)
            
        return True

    def is_user_admin(self, chat_id, user_id):
        """Проверить, является ли пользователь администратором"""
        url = self.base_url + "getChatAdministrators"
        params = {"chat_id": chat_id}
        
        try:
            response = requests.post(url, json=params, timeout=10)
            data = response.json()
            if data.get("ok"):
                admins = [admin["user"]["id"] for admin in data["result"]]
                return user_id in admins
        except:
            pass
        return False

    def show_main_menu(self, chat_id):
        """Главное меню"""
        text = """
🤖 <b>Бот-модератор ночного режима</b>

<b>Режим работы:</b>
• 💾 Сообщения сохраняются во время ночного режима
• 🗑️ Все сообщения удаляются в конце периода
• 📊 Вы получаете отчет об удаленных сообщениях

Выберите действие:
"""
        buttons = [
            "📋 Мои чаты",
            "➕ Добавить чаt", 
            "❓ Помощь"
        ]
        
        keyboard = self.create_keyboard(buttons, 2)
        self.send_message(chat_id, text, keyboard)

    def show_my_chats(self, user_id, chat_id):
        """Показать список чатов с инлайн кнопками"""
        self.cursor.execute('SELECT chat_id, chat_title, night_mode_enabled, start_time, end_time FROM chat_settings WHERE is_active = 1')
        chats = self.cursor.fetchall()
        
        if not chats:
            text = """
📋 <b>Мои чаты</b>

❌ У вас нет настроенных чатов.

Нажмите "➕ Добавить чат" чтобы добавить первый чат.
"""
            keyboard = self.create_keyboard(["➕ Добавить чат", "🔙 Главное меню"])
            self.send_message(chat_id, text, keyboard)
        else:
            text = "📋 <b>Мои чаты</b>\n\nВыберите чат для настройки:\n"
            
            # Создаем инлайн кнопки для каждого чата
            keyboard_buttons = []
            for chat_id_db, chat_title, enabled, start_time, end_time in chats:
                status = "🟢" if enabled else "🔴"
                chat_name = chat_title or f"Чат {chat_id_db}"
                button_text = f"{status} {chat_name}"
                keyboard_buttons.append([(button_text, f"select_chat_{chat_id_db}")])
            
            keyboard_buttons.append([("🔙 Главное меню", "main_menu")])
            
            inline_keyboard = self.create_inline_keyboard(keyboard_buttons)
            self.send_message(chat_id, text, inline_keyboard)

    def show_chat_settings(self, chat_id, target_chat_id, user_id):
        """Настройки конкретного чата"""
        settings = self.get_chat_settings(target_chat_id)
        
        if not settings:
            self.send_message(chat_id, "❌ Чат не найден")
            return
            
        # Безопасное получение значений с проверкой длины кортежа
        night_mode_enabled = settings[2] if len(settings) > 2 else 0
        start_time = settings[3] if len(settings) > 3 else "23:00"
        end_time = settings[4] if len(settings) > 4 else "05:00"
        welcome_msg = settings[5] if len(settings) > 5 else "🌙 Ночной режим активирован!"
        is_night_mode_active = settings[9] if len(settings) > 9 else 0
        
        status = "🟢 ВКЛЮЧЕН" if night_mode_enabled else "🔴 ВЫКЛЮЧЕН"
        
        # Проверяем текущий статус
        current_status = "🔴 АКТИВЕН (сообщения сохраняются)" if is_night_mode_active else "🟢 ОЖИДАНИЕ"
        
        text = f"""
⚙️ <b>Настройки чата</b>

🆔 ID: <code>{target_chat_id}</code>
🌙 Режим: {status}
⏰ Время: {start_time} - {end_time}
📊 Статус: {current_status}
📝 Сообщение: {welcome_msg}

Выберите действие:
"""
        
        # Создаем инлайн кнопки для управления
        toggle_text = "🔴 Выключить" if night_mode_enabled else "🟢 Включить"
        keyboard_buttons = [
            [(toggle_text, f"toggle_mode_{target_chat_id}")],
            [("⏰ Изменить время начала", f"edit_start_{target_chat_id}")],
            [("⏰ Изменить время окончания", f"edit_end_{target_chat_id}")],
            [("📝 Изменить сообщение", f"edit_message_{target_chat_id}")],
            [("🔙 К списку чатов", "main_menu")]
        ]
        
        inline_keyboard = self.create_inline_keyboard(keyboard_buttons)
        self.send_message(chat_id, text, inline_keyboard)

    def show_help(self, chat_id):
        """Помощь"""
        text = """
❓ <b>Помощь по боту (режим отложенного удаления)</b>

<b>Как работает:</b>
• Сообщения во время ночного режима СОХРАНЯЮТСЯ
• В конце периода все сообщения УДАЛЯЮТСЯ разом
• Вы получаете отчет об удаленных сообщениях

<b>Преимущества:</b>
• 💬 Диалоги видны во время ночного режима
• 🗑️ Автоматическая очистка в указанное время
• 📊 Отчет о проделанной работе

<b>Команды в группе:</b>
/id - Получить ID чата
/status - Статус режима  
/test_night - Проверить ночной режим
/force_cleanup - Принудительная очистка (админы)

<b>Настройка:</b>
1. Добавьте бота в группу как администратора
2. Дайте права на удаление сообщений
3. Настройте время через личный чат с ботом
"""
        buttons = ["🔙 Главное меню"]
        keyboard = self.create_keyboard(buttons)
        self.send_message(chat_id, text, keyboard)

    def show_group_help(self, chat_id):
        """Помощь в группе"""
        text = f"""
🤖 <b>Бот ночного режима</b>

<b>Команды:</b>
/id - Получить ID чата
/status - Статус режима  
/test_night - Проверить ночной режим

<b>ID этого чата:</b> <code>{chat_id}</code>

<b>Для настройки:</b>
1. Напишите боту в личные сообщения
2. Используйте ID выше
3. Настройте время и сообщения
"""
        self.send_message(chat_id, text)

    def show_group_status(self, chat_id):
        """Статус в группе"""
        settings = self.get_chat_settings(chat_id)
        
        if settings and len(settings) > 2 and settings[2]:
            is_night_mode_active = settings[9] if len(settings) > 9 else 0
            if is_night_mode_active:
                current_session = self.get_current_session(chat_id)
                self.cursor.execute('SELECT COUNT(*) FROM saved_messages WHERE chat_id = ? AND night_mode_session = ?', 
                                  (chat_id, current_session))
                saved_count = self.cursor.fetchone()[0]
                
                status = "🔴 АКТИВЕН (сообщения сохраняются)"
                end_time = settings[4] if len(settings) > 4 else "05:00"
                info = f"💾 Сохранено: {saved_count} сообщений\n⏰ Удаление в: {end_time}"
            else:
                status = "🟢 ВКЛЮЧЕН (ожидание)"
                start_time = settings[3] if len(settings) > 3 else "23:00"
                info = f"⏰ Начнется в: {start_time}"
        else:
            status = "🔴 ВЫКЛЮЧЕН"
            info = "Режим отключен"
        
        text = f"""
📊 <b>Статус ночного режима</b>

🌙 Режим: {status}
{info}
🆔 ID: <code>{chat_id}</code>

💡 Сообщения сохраняются и удаляются в конце периода
"""
        self.send_message(chat_id, text)

    # ==== БАЗА ДАННЫХ МЕТОДЫ ====

    def get_chat_settings(self, chat_id):
        """Получить настройки чата"""
        self.cursor.execute('SELECT * FROM chat_settings WHERE chat_id = ?', (chat_id,))
        return self.cursor.fetchone()

    def enable_night_mode(self, chat_id):
        """Включить ночной режим"""
        try:
            self.cursor.execute('UPDATE chat_settings SET night_mode_enabled = 1 WHERE chat_id = ?', (chat_id,))
            self.conn.commit()
            self.logger.info(f"✅ Режим включен для чата {chat_id}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка включения: {e}")

    def disable_night_mode(self, chat_id):
        """Выключить ночной режим"""
        try:
            self.cursor.execute('UPDATE chat_settings SET night_mode_enabled = 0 WHERE chat_id = ?', (chat_id,))
            self.conn.commit()
            self.logger.info(f"✅ Режим выключен для чата {chat_id}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка выключения: {e}")

    def update_start_time(self, chat_id, start_time):
        """Обновить время начала"""
        try:
            self.cursor.execute('UPDATE chat_settings SET start_time = ? WHERE chat_id = ?', (start_time, chat_id))
            self.conn.commit()
            self.logger.info(f"✅ Время начала обновлено: {start_time} для чата {chat_id}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления времени: {e}")

    def update_end_time(self, chat_id, end_time):
        """Обновить время окончания"""
        try:
            self.cursor.execute('UPDATE chat_settings SET end_time = ? WHERE chat_id = ?', (end_time, chat_id))
            self.conn.commit()
            self.logger.info(f"✅ Время окончания обновлено: {end_time} для чата {chat_id}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления времени: {e}")

    def update_welcome_message(self, chat_id, message):
        """Обновить приветственное сообщение"""
        try:
            self.cursor.execute('UPDATE chat_settings SET welcome_message = ? WHERE chat_id = ?', (message, chat_id))
            self.conn.commit()
            self.logger.info(f"✅ Сообщение обновлено для чата {chat_id}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления сообщения: {e}")

    def is_valid_time(self, time_str):
        """Проверить валидность времени"""
        try:
            datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

def main():
    BOT_TOKEN = "8416503414:AAHmAD0tstjerCS4itAEwZ7s9WYcH2JF-xM"
    
    bot = NightModeBot(BOT_TOKEN)
    
    print("🚀 Бот-модератор запущен!")
    print("💾 Режим отложенного удаления активирован")
    print("⏰ Сообщения сохраняются и удаляются в конце периода")
    print("📱 Напишите /start в Telegram")
    print("⏹️ Ctrl+C для остановки")
    
    last_update_id = 0
    
    try:
        while True:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {"offset": last_update_id + 1, "timeout": 25}
                
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok") and data.get("result"):
                        for update in data["result"]:
                            last_update_id = update["update_id"]
                            
                            # Обработка обычных сообщений (всех типов)
                            if "message" in update:
                                message = update["message"]
                                user_id = message["from"]["id"]
                                chat_id = message["chat"]["id"]
                                
                                bot.handle_message(message, user_id, chat_id)
                            
                            # Обработка callback от инлайн кнопок
                            elif "callback_query" in update:
                                callback = update["callback_query"]
                                callback_data = callback.get("data", "")
                                user_id = callback["from"]["id"]
                                chat_id = callback["message"]["chat"]["id"]
                                message_id = callback["message"]["message_id"]
                                
                                bot.handle_callback(callback_data, user_id, chat_id, message_id)
                
                time.sleep(0.5)
                
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                time.sleep(5)
                
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")

if __name__ == "__main__":
    main()
