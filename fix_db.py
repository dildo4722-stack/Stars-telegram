import sqlite3

# Укажи здесь точное имя файла своей базы
conn = sqlite3.connect('database.db') 
cursor = conn.cursor()

cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('platega_fee', '5.0')")
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('platega_enabled', '1')")

conn.commit()
conn.close()
print("Настройки Platega успешно добавлены в базу!")