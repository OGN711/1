import requests
from datetime import datetime, timedelta
import feedparser
import asyncio
from aiogram import Bot
import logging
import re
import time
from typing import List, Dict

# --- НАСТРОЙКИ (ЗАМЕНИТЕ НА ВАШИ ДАННЫЕ) ---
TELEGRAM_TOKEN = '8330755119:AAFIZbQbGVJMCWU8tAH9Xo_I9Q3BTcgKVA8'   # Получите у @BotFather
DEEPSEEK_API_KEY = 'sk-6032043820c746508f59c79abbc873e8'   # Создайте на platform.deepseek.com
CHANNEL_ID = '-1001256551300'                  # ID вашего канала
# --------------------------------------------

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_news_from_rss() -> List[Dict]:
    """Получает новости о технологиях за последние 24 часа из RSS-ленты Google Новостей."""
    # Формируем URL для поиска по ключевым словам в Google Новостях
    rss_url = "https://news.google.com/rss/search?q=гаджеты&hl=ru&gl=RU&ceid=RU:ru"
    
    logging.info(f"Парсинг RSS-ленты: {rss_url}")
    feed = feedparser.parse(rss_url)
    
    news_list = []
    yesterday = datetime.now() - timedelta(days=1)
    
    for entry in feed.entries:
        # Парсим дату публикации
        published_time = None
        if hasattr(entry, 'published_parsed'):
            published_time = datetime(*entry.published_parsed[:6])
        
        # Если дата есть и она за последние 24 часа, добавляем новость
        if published_time and published_time > yesterday:
            news_list.append({
                'title': entry.title,
                'summary': entry.summary if hasattr(entry, 'summary') else '',
                'link': entry.link,
                'published': published_time
            })
    
    # Ограничиваем количество новостей для предотвращения таймаута
    news_list = news_list[:10]
    logging.info(f"Найдено {len(news_list)} новостей за последние 24 часа.")
    return news_list

def clean_markdown(text: str) -> str:
    """Очищает текст от проблемных Markdown-символов для Telegram."""
    # Экранируем специальные символы Markdown
    special_chars = r'[_*`\[\]()~>#+\-=|{}.!]'
    text = re.sub(special_chars, lambda m: '\\' + m.group(0), text)
    return text

def generate_digest_with_deepseek(news_list: List[Dict]) -> str:
    """Отправляет список новостей в DeepSeek и получает обратно связный дайджест с повторами при ошибках."""
    if not news_list:
        return "За последние 24 часа не найдено новостей по теме технологий и гаджетов."
    
    # Формируем промпт для DeepSeek на основе собранных новостей
    news_text = "\n\n".join([f"• {item['title']}" for item in news_list[:8]])  # Берём только заголовки для экономии
    
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%d.%m.%Y')
    
    prompt = f"""
    На основе этих заголовков новостей о технологиях и гаджетах за {yesterday_str} составь связный и интересный дайджест.
    
    Требования:
    - Объем: примерно 150-200 слов.
    - Стиль: информативный, увлекательный, как для блога о технологиях.
    - Структура: начни с краткого введения, затем перечисли 3-5 ключевых новостей.
    - В конце добавь небольшую рубрику "Быстрые факты" с 2-3 краткими новостями.
    - НЕ используй Markdown-символы (*, _, [, ], `) в тексте. Пиши обычным текстом.
    - Язык: русский, живой и современный.
    
    Вот заголовки новостей для обработки:
    {news_text}
    """
    
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "Ты — опытный технологический журналист, который пишет увлекательные дайджесты. Ты НЕ используешь Markdown-форматирование."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 800
    }
    
    # Повторяем запрос до 3 раз при таймауте
    for attempt in range(3):
        try:
            logging.info(f"Попытка {attempt + 1} из 3 отправить запрос к DeepSeek API...")
            response = requests.post(url, headers=headers, json=data, timeout=90)
            response.raise_for_status()
            digest = response.json()['choices'][0]['message']['content']
            logging.info("Дайджест успешно получен от DeepSeek")
            return digest
        except requests.exceptions.Timeout:
            logging.warning(f"Попытка {attempt + 1} из 3 не удалась (таймаут). Повтор через 10 секунд...")
            if attempt < 2:
                time.sleep(10)
            else:
                logging.error("Все попытки запроса к DeepSeek API не удались.")
                return "⚠️ Сервер DeepSeek временно недоступен. Попробуйте позже."
        except Exception as e:
            logging.error(f"Ошибка при запросе к DeepSeek API: {e}")
            if attempt < 2:
                time.sleep(5)
            else:
                return f"⚠️ Ошибка при генерации дайджеста: {str(e)}"
    
    return "⚠️ Не удалось обработать новости. Пожалуйста, попробуйте позже."

async def send_news_digest():
    """Основная функция: получает новости, генерирует дайджест и отправляет в Telegram."""
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        # Шаг 1: Парсим RSS и получаем сырые новости
        raw_news = fetch_news_from_rss()
        
        if not raw_news:
            await bot.send_message(chat_id=CHANNEL_ID, text="📭 За последние 24 часа не найдено новостей по теме технологий и гаджетов.")
            return
        
        # Шаг 2: Отправляем новости в DeepSeek для создания дайджеста
        logging.info("Отправка новостей в DeepSeek для создания дайджеста...")
        digest = generate_digest_with_deepseek(raw_news)
        
        # Шаг 3: Отправляем финальный дайджест в Telegram-канал
        today_str = datetime.now().strftime('%d.%m.%Y')
        message = f"🤖 Технологический дайджест за {today_str}\n\n{digest}"
        
        # Очищаем сообщение от проблемных Markdown-символов
        safe_message = clean_markdown(message)
        
        # Отправляем сообщение БЕЗ Markdown форматирования для надёжности
        await bot.send_message(chat_id=CHANNEL_ID, text=safe_message)
        logging.info("Дайджест успешно отправлен в канал.")
        
    except Exception as e:
        logging.error(f"Произошла ошибка: {e}")
        # Пытаемся отправить сообщение об ошибке в канал
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=f"⚠️ Произошла ошибка при формировании дайджеста. Попробуйте позже.")
        except:
            pass
    finally:
        await bot.session.close()

async def test_send():
    """Тестовая функция для проверки отправки простого сообщения."""
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text="🤖 Бот запущен и работает!")
        logging.info("Тестовое сообщение отправлено")
    except Exception as e:
        logging.error(f"Ошибка при отправке тестового сообщения: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    import sys
    
    # Проверяем аргументы командной строки
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Тестовый режим
        asyncio.run(test_send())
    else:
        # Основной режим
        asyncio.run(send_news_digest())
