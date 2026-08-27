# Ansible Vault: Алгоритмы шифрования

## Определения

- **Криптографическая схема (Cipher Suite)**: Набор алгоритмов, обеспечивающих защиту данных. В Ansible Vault используется фиксированная схема, которую пользователь не может изменить, что гарантирует высокий уровень безопасности и совместимость между версиями.
- **PBKDF2 (Password-Based Key Derivation Function 2)**: Функция формирования ключа на основе пароля. Она делает перебор паролей (брутфорс) вычислительно дорогим за счет тысяч итераций хеширования. В Ansible используется реализация `PBKDF2-HMAC-SHA256`.
- **KDF (Key Derivation Function)**: Функция формирования ключа, преобразующая входной секрет (пароль) в криптографически стойкие ключи для шифрования и аутентификации.
- **HMAC (Hash-based Message Authentication Code)**: Код аутентификации сообщений, использующий хеш-функцию. Обеспечивает проверку целостности и подлинности данных, предотвращая их модификацию в зашифрованном виде.
- **CTR (Counter Mode)**: Режим счетчика в блочном шифровании, превращающий блочный шифр в потоковый. Позволяет шифровать данные произвольной длины без необходимости дополнения (padding) и обеспечивает высокую производительность за счет параллелизации.
- **Salt (Соль)**: Случайные данные, добавляемые к паролю перед хешированием. Гарантирует, что одинаковые пароли дают разные ключи, предотвращая атаки по таблицам rainbow tables.
- **Data Tagging**: Механизм отслеживания происхождения данных в Ansible, предотвращающий случайные утечки зашифрованных значений в логи CI/CD (доступен с версии ansible-core 2.19+).

## Предварительные требования

Перед работой с алгоритмами шифрования Ansible Vault убедитесь в наличии:

- **Python**: версия 3.8+ (для совместимости с ansible-core 2.12+).
- **Библиотека `cryptography`**: установите через `pip install cryptography` (обычно уже установлена как зависимость ansible-core).
- **OpenSSL**: для ручных операций с сертификатами (опционально).
- **Хранилище паролей**: файл или скрипт с правами доступа `chmod 600` (для тестирования алгоритмов).

Для проверки версий:
```bash
python3 -c "import cryptography; print(cryptography.__version__)"
openssl version
ansible --version | head -1
```

## Основные концепции

### Компоненты защиты

Ansible Vault реализует схему **Encrypt-then-MAC** (шифрование, затем аутентификация). Это современный стандарт безопасности, гарантирующий, что любые изменения в зашифрованном файле будут обнаружены ДО попытки расшифровки.

| Компонент | Технология | Технические подробности |
| :--- | :--- | :--- |
| **Шифрование** | `AES-256-CTR` | Симметричный алгоритм с ключом 256 бит. Режим CTR превращает его в потоковый шифр, что исключает атаки на дополнение (padding oracle attacks). |
| **Производная ключа** | `PBKDF2-HMAC-SHA256` | Использует SHA-256 как базовую хеш-функцию. Зафиксировано **10 000 итераций** и 32-байтная случайная соль (Salt), генерируемая при каждом создании файла. |
| **Целостность (MAC)** | `HMAC-SHA256` | Вычисляется от зашифрованного содержимого. Гарантирует целостность: если байты файла изменены, Ansible выдаст ошибку аутентификации. |
| **Крипто-библиотека** | `cryptography` | Современная Python-библиотека (на базе OpenSSL), используемая в `ansible-core` для всех низкоуровневых операций. |

### Процесс формирования ключа (KDF Details)

При выполнении расшифровки или проверки целостности Ansible выполняет следующие этапы деривации ключей:

1. **Извлечение метаданных**: Из заголовка файла считывается соль (Salt, 32 байта) и алгоритм.
2. **Итеративное хеширование**: Мастер-пароль и соль проходят через 10 000 итераций PBKDF2.
3. **Генерация байтового потока**: На выходе KDF формируется **80 байт** (640 бит) ключевого материала, который разделяется на три части:
   - **Байты 0-31 (256 бит)**: Ключ шифрования (Cipher Key) для AES-256.
   - **Байты 32-63 (256 бит)**: Ключ для вычисления и проверки HMAC (MAC Key).
   - **Байты 64-79 (128 бит)**: Вектор инициализации (IV — Initialization Vector) для режима CTR.

### Ограничения безопасности и атаки на GPU (2024-2026)

Количество итераций (10 000) в Ansible Vault является историческим компромиссом между безопасностью и скоростью работы на слабых управляющих узлах. По современным меркам (рекомендации OWASP на 2025 год — от 600 000 итераций) это значение считается **низким**.

**Риски:** При компрометации зашифрованного файла злоумышленник может использовать мощные видеокарты (GPU) для высокоскоростного перебора паролей.
**Защита:** Единственный надежный способ компенсировать низкое число итераций — использование **мастер-паролей длиной от 20 символов** с высокой энтропией (случайные фразы, комбинации символов).

### Версии формата и заголовков

Первая строка файла определяет логику обработки секретов:
- `$ANSIBLE_VAULT;1.1;AES256`: Классический формат (Ansible 1.5+). Поддерживает только один пароль.
- `$ANSIBLE_VAULT;1.2;AES256;prod`: Современный формат (Ansible 2.4+). Включае метку **Vault ID**, что позволяет Ansible мгновенно выбрать нужный ключ из списка предоставленных (вместо перебора всех).

**Data Tagging и EncryptedString (Core 2.19+):**
В последних версиях Ansible внедрен внутренний тип данных `EncryptedString`. Это развитие системы отслеживания секретов в памяти процесса. Объект секрета «помечается», и если разработчик попытается вывести его через модуль `debug` без явного указания параметров, Ansible блокирует вывод или заменяет его на `[VALUE_IS_ENCRYPTED]`, предотвращая случайные утечки в логи CI/CD.

## Практические сценарии

### Сценарий 1: Анализ заголовка зашифрованного файла

Для диагностики проблем с Vault ID или версией алгоритма:

```bash
# Просмотр заголовка
head -n 1 secrets.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod

# Извлечение метки Vault ID
head -1 secrets.yml | cut -d';' -f4
# → prod

# Проверка версии формата
head -1 secrets.yml | cut -d';' -f2
# → 1.2
```

### Сценарий 2: Принудительное обновление формата (Rekey)

При переносе старых проектов (версии 1.1) на современные стандарты:

```bash
# Перевод файла в формат 1.2 с новой меткой
ansible-vault rekey --vault-id prod@prompt secrets.yml

# Перешифровка всех файлов в каталоге
find group_vars -name "*.yml" -exec ansible-vault rekey --vault-id dev@.vault_pass_dev {} \;

# Перешифровка с указанием нового Vault ID
ansible-vault rekey --vault-id old@prompt --new-vault-id new@prompt secrets.yml
```

### Сценарий 3: Бенчмаркинг времени работы PBKDF2

Измерение времени, затрачиваемого на деривацию ключа для конкретного пароля:

```python
#!/usr/bin/env python3
# benchmark_pbkdf2.py

import time
import hashlib
import os

def benchmark_pbkdf2(password: str, iterations: int = 10000, salt: bytes = None):
    """Бенчмарк PBKDF2-HMAC-SHA256 с фиксированной солью (32 байта)."""
    if salt is None:
        salt = os.urandom(32)

    start = time.perf_counter()
    dk = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode(),
        salt,
        iterations,
        dklen=80  # 3 Cipher Key + 32 MAC Key + 16 IV
    )
    elapsed = time.perf_counter() - start

    cipher_key = dk[:32].hex()
    mac_key = dk[32:64].hex()
    iv = dk[64:80].hex()

    return {
        'time_ms': round(elapsed * 1000, 2),
        'cipher_key': cipher_key[:16] + '...',
        'mac_key': mac_key[:16] + '...',
        'iv': iv[:16] + '...',
        'iterations': iterations
    }

if __name__ == '__main__':
    import sys
    password = sys.argv[1] if len(sys.argv) > 1 else 'test_password'
    result = benchmark_pbkdf2(password)
    print(f"Password: {password[:4]}...{password[-4:]}")
    print(f"Iterations: {result['iterations']}")
    print(f"Time: {result['time_ms']} ms")
    print(f"Cipher Key: {result['cipher_key']}")
    print(f"MAC Key: {result['mac_key']}")
    print(f"IV: {result['iv']}")
```

Запуск:
```bash
python3 benchmark_pbkdf2.py "MySecretPassword"
```

### Сценарий 4: Проверка целостности зашифрованного файла

Валидация HMAC без расшифровки (для обнаружения повреждений):

```bash
#!/bin/bash
# check_vault_integrity.sh

VAULT_FILE="${1:?Укажите путь к зашифрованному файлу}"

if [ ! -f "$VAULT_FILE" ]; then
    echo "Файл не найден: $VAULT_FILE"
    exit 1
fi

# Проверка заголовка
HEADER=$(head -1 "$VAULT_FILE")
if [[ ! "$HEADER" =~ ^\$ANSIBLE_VAULT ]]; then
    echo "Ошибка: не Vault-файл (отсутствует заголовок)"
    exit 1
fi

# Попытка расшифровки (проверка HMAC)
if ansible-vault view "$VAULT_FILE" > /dev/null 2>&1; then
    echo "OK: целостность подтверждена ($HEADER)"
else
    echo "Ошибка: HMAC не совпадает или неверный пароль"
    exit 1
fi
```

Использование:
```bash
chmod +x check_vault_integrity.sh
./check_vault_integrity.sh group_vars/prod/vault.yml
```

### Сценарий 5: Сравнение производительности AES-256-CTR vs AES-256-CBC

Измерение разницы в скорости между режимами шифрования:

```python
#!/usr/bin/env python3
# benchmark_modes.py

import time
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

def benchmark_mode(mode_name, mode_obj, data, key, iv):
    cipher = Cipher(algorithms.AES(key), mode_obj)
    encryptor = cipher.encryptor()

    start = time.perf_counter()
    ct = encryptor.update(data) + encryptor.finalize()
    elapsed = time.perf_counter() - start

    return {
        'mode': mode_name,
        'time_ms': round(elapsed * 1000, 3),
        'throughput_mbps': round((len(data) / 1024 / 1024) / elapsed, 2),
        'ciphertext_len': len(ct)
    }

if __name__ == '__main__':
    key = os.urandom(32)  # 256 bits
    iv = os.urandom(16)   # 128 bits
    data = os.urandom(1024 * 1024)  # 1 MB

    # CTR (как в Ansible Vault)
    ctr_result = benchmark_mode(
        'AES-256-CTR',
        modes.CTR(iv),
        data, key, iv
    )

    # CBC (альтернатива)
    cbc_result = benchmark_mode(
        'AES-256-CBC',
        modes.CBC(iv),
        data, key, iv
    )

    print("Результаты бенчмарка (1 МБ данных):")
    print(f"  CTR: {ctr_result['time_ms']}ms ({ctr_result['throughput_mbps']} MB/s)")
    print(f"  CBC: {cbc_result['time_ms']}ms ({cbc_result['throughput_mbps']} MB/s)")
    print(f"\nCTR быстрее на {(cbc_result['time_ms'] / ctr_result['time_ms'] - 1) * 100:.1f}%")
```

### Сценарий 6: Визуализация структуры зашифрованного файла

Анализ и визуализация компонентов Vault-файла:

```bash
#!/bin/bash
# visualize_vault_structure.sh

VAULT_FILE="${1:?Укажите путь к зашифрованному файлу}"

if [ ! -f "$VAULT_FILE" ]; then
    echo "Файл не найден: $VAULT_FILE"
    exit 1
fi

HEADER=$(head -1 "$VAULT_FILE")
VERSION=$(echo "$HEADER" | cut -d';' -f2)
ALGORITHM=$(echo "$HEADER" | cut -d';' -f3)
VAULT_ID=$(echo "$HEADER" | cut -d';' -f4)

echo "=== Структура Vault-файла ==="
echo "Путь: $VAULT_FILE"
echo "Размер: $(wc -c < "$VAULT_FILE") байт"
echo ""
echo "Заголовок: $HEADER"
echo "├── Версия формата: $VERSION"
echo "├── Алгоритм: $ALGORITHM"
echo "├── Vault ID: ${VAULT_ID:-<отсутствует>}"
echo "└── Данные: $(wc -l < "$VAULT_FILE") строк"
echo ""

if [ "$VERSION" = "1.2" ]; then
    echo "✓ Формат 1.2: поддержка Vault ID, быстрый выбор ключа"
else
    echo "⚠ Формат 1.1: нет Vault ID, перебор всех ключей"
fi

echo ""
echo "=== Сравнение версий ==="
echo "Формат 1.1: \$ANSIBLE_VAULT;1.1;AES256"
echo "  • Один пароль, перебор всех ключей"
echo "  • Медленно при большом количестве хранилищ"
echo ""
echo "Формат 1.2: \$ANSIBLE_VAULT;1.2;AES256;label"
echo "  • Метка Vault ID, мгновенный выбор ключа"
echo "  • Рекомендуется для новых проектов"
```

### Сценарий 7: Тестирование стойкости пароля к перебору

Оценка времени перебора для различных длин и энтропии паролей:

```python
#!/usr/bin/env python3
# password_strength.py

import math

def entropy_chars(password: str) -> float:
    """Энтропия пароля на основе множества символов."""
    charset = 0
    if any(c.islower() for c in password): charset += 26
    if any(c.isupper() for c in password): charset += 26
    if any(c.isdigit() for c in password): charset += 10
    if any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password): charset += 32
    return len(password) * math.log2(charset) if charset > 0 else 0

def estimate_crack_time(entropy_bits: float, guesses_per_second: float = 1e10) -> float:
    """Оценка времени перебора в секундах (10 млрд попыток/сек — GPU)."""
    combinations = 2 ** entropy_bits
    return combinations / guesses_per_second / 2  # В среднем нужно перебрать половину

def format_time(seconds: float) -> str:
    """Форматирование времени в читаемый вид."""
    if seconds < 60: return f"{seconds:.1f} секунд"
    if seconds < 3600: return f"{seconds / 60:.1f} минут"
    if seconds < 86400: return f"{seconds / 3600:.1f} часов"
    if seconds < 31536000: return f"{seconds / 86400:.1f} дней"
    if seconds < 31536000 * 1000: return f"{seconds / 31536000:.1f} лет"
    return f"{seconds / 31536000 / 1000:.1f} тысяч лет"

if __name__ == '__main__':
    test_passwords = [
        "password",
        "MyPassword123",
        "MyStr0ng!P@ssw0rd",
        "Correct-Horse-Battery-Staple",
        "Xk9#mP2$vL8qR!nY5wZ7",
    ]

    print("=== Анализ стойкости паролей ===\n")
    print(f"{'Пароль':<30} {'Энтропия':<12} {'Время перебора'}")
    print("-" * 70)

    for pwd in test_passwords:
        entropy = entropy_chars(pwd)
        crack_time = estimate_crack_time(entropy)
        display_pwd = pwd[:27] + '...' if len(pwd) > 30 else pwd
        print(f"{display_pwd:<30} {entropy:<10.1f} бит  {format_time(crack_time)}")
```

Запуск:
```bash
python3 password_strength.py
```

### Сценарий 8: Миграция с Vault 1.1 на 1.2 в массовом порядке

Скрипт для автоматического обновления формата всех зашифрованных файлов в проекте:

```bash
#!/bin/bash
# migrate_vault_1_1_to_1_2.sh

VAULT_PASS="${1:?Укажите путь к файлу пароля}"
VAULT_ID_LABEL="${2:-default}"
REPO_ROOT="${3:-.}"

echo "Миграция Vault-файлов в формат 1.2..."
echo "  Vault ID: $VAULT_ID_LABEL"
echo "  Каталог: $REPO_ROOT"

COUNT=0
ERRORS=0

find "$REPO_ROOT" -name "*.yml" -type f | while read -r file; do
    HEADER=$(head -1 "$file" 2>/dev/null)
    if [[ "$HEADER" =~ ^\$ANSIBLE_VAULT\;1\.1 ]]; then
        echo -n "  Обновление: $file ... "
        if ansible-vault rekey --vault-id "$VAULT_ID_LABEL@${VAULT_PASS}" \
                               --new-vault-id "$VAULT_ID_LABEL@${VAULT_PASS}" \
                               "$file" 2>/dev/null; then
            echo "OK"
            COUNT=$((COUNT + 1))
        else
            echo "ОШИБКА"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done

echo ""
echo "Итого: обновлено $COUNT файлов, ошибок: $ERRORS"
```

### Сценарий 9: Проверка совместимости версий Ansible

Определение минимальной версии Ansible для работы с зашифрованными файлами:

```bash
#!/bin/bash
# check_vault_compatibility.sh

VAULT_FILE="${1:?Укажите путь к зашифрованному файлу}"
CURRENT_ANSIBLE=$(ansible --version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

if [ ! -f "$VAULT_FILE" ]; then
    echo "Файл не найден: $VAULT_FILE"
    exit 1
fi

HEADER=$(head -1 "$VAULT_FILE")
VERSION=$(echo "$HEADER" | cut -d';' -f2)
VAULT_ID=$(echo "$HEADER" | cut -d';' -f4)

echo "=== Анализ совместимости ==="
echo "Текущая версия Ansible: $CURRENT_ANSIBLE"
echo "Файл: $VAULT_FILE"
echo "Формат: $VERSION"

if [ "$VERSION" = "1.2" ]; then
    echo "Vault ID: ${VAULT_ID:-<отсутствует>}"
    echo ""
    echo "Требования к версии Ansible:"
    echo "  • Формат 1.2 с Vault ID: Ansible >= 2.4"
    echo "  • EncryptedString (ansible-core): ansible-core >= 2.19"
    echo ""
    if [[ "$CURRENT_ANSIBLE" < "2.4" ]]; then
        echo "⚠ ВНИМАНИЕ: Текущая версия не поддерживает Vault ID!"
        echo "  Рекомендуется обновить Ansible до версии 2.4+"
    else
        echo "✓ Текущая версия совместима"
    fi
else
    echo ""
    echo "Формат 1.1 совместим со всеми версиями Ansible (1.5+)"
    echo "Рекомендуется обновить до формата 1.2 для:"
    echo "  • Быстрого выбора ключа по Vault ID"
    echo "  • Улучшенной безопасности"
fi
```

### Сценарий 10: Анализ криптографических свойств файла

Проверка случайности соли и распределения байтов зашифрованных данных:

```python
#!/usr/bin/env python3
# analyze_vault_crypto.py

import sys
import math
from collections import Counter

def analyze_vault_file(filepath: str):
    """Анализ криптографических свойств зашифрованного Vault-файла."""
    with open(filepath, 'rb') as f:
        data = f.read()

    lines = data.split(b'\n')
    header = lines[0].decode('utf-8', errors='ignore')
    ciphertext = b''.join(lines[1:])

    print(f"=== Анализ: {filepath} ===")
    print(f"Заголовок: {header}")
    print(f"Общий размер: {len(data)} байт")
    print(f"Размер шифротекста: {len(ciphertext)} байт")
    print()

    # Анализ энтропии шифротекста
    byte_counts = Counter(ciphertext)
    total = len(ciphertext)
    entropy = -sum((count/total) * math.log2(count/total) for count in byte_counts.values())

    print(f"Энтропия шифротекста: {entropy:.3f} бит/байт (максимум 8.0)")
    print(f"Уникальных байтов: {len(byte_counts)}/256")
    print()

    # Распределение частот (для визуального анализа)
    print("Распределение байтов (первые 64):")
    freq_bar = ""
    max_count = max(byte_counts.values())
    for i in range(64):
        count = byte_counts.get(i, 0)
        bar_len = int(count / max_count * 20) if max_count > 0 else 0
        freq_bar += "█" * bar_len
    print(f"  {freq_bar}")
    print()

    if entropy > 7.5:
        print("✓ Высокая энтропия — данные хорошо зашифрованы")
    elif entropy > 5.0:
        print("⚠ Средняя энтропия — возможны проблемы с шифрованием")
    else:
        print("✗ Низкая энтропия — данные могут быть не зашифрованы")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python3 analyze_vault_crypto.py <vault_file>")
        sys.exit(1)
    analyze_vault_file(sys.argv[1])
```

### Сценарий 11: Оптимизация времени расшифровки для больших файлов

Тестирование производительности при различных размерах данных:

```python
#!/usr/bin/env python3
# benchmark_vault_performance.py

import time
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def benchmark_vault_workflow(password: str, data_size_mb: int):
    """Бенчмарк полного цикла Vault: KDF + шифрование + расшифрование."""
    salt = os.urandom(32)
    iv = os.urandom(16)
    data = os.urandom(data_size_mb * 1024 * 1024)

    # Этап 1: KDF (PBKDF2)
    start_kdf = time.perf_counter()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=80,
        salt=salt,
        iterations=10000,
    )
    key_material = kdf.derive(password.encode())
    cipher_key = key_material[:32]
    mac_key = key_material[32:64]
    elapsed_kdf = time.perf_counter() - start_kdf

    # Этап 2: Шифрование (AES-256-CTR)
    start_enc = time.perf_counter()
    cipher = Cipher(algorithms.AES(cipher_key), modes.CTR(iv))
    encryptor = cipher.encryptor()
    ct = encryptor.update(data) + encryptor.finalize()
    elapsed_enc = time.perf_counter() - start_enc

    # Этап 3: Расшифрование
    start_dec = time.perf_counter()
    cipher = Cipher(algorithms.AES(cipher_key), modes.CTR(iv))
    decryptor = cipher.decryptor()
    pt = decryptor.update(ct) + decryptor.finalize()
    elapsed_dec = time.perf_counter() - start_dec

    return {
        'data_size_mb': data_size_mb,
        'kdf_ms': round(elapsed_kdf * 1000, 1),
        'encrypt_ms': round(elapsed_enc * 1000, 1),
        'decrypt_ms': round(elapsed_dec * 1000, 1),
        'total_ms': round((elapsed_kdf + elapsed_enc + elapsed_dec) * 1000, 1),
        'throughput_mbps': round(data_size_mb / (elapsed_enc + elapsed_dec), 1) if (elapsed_enc + elapsed_dec) > 0 else 0
    }

if __name__ == '__main__':
    print("=== Бенчмарк производительности Ansible Vault ===\n")
    print(f"{'Размер':<10} {'KDF':<10} {'Шифр.':<10} {'Расш.':<10} {'Итого':<10} {'Пропуск.'}")
    print("-" * 60)

    for size_mb in [1, 10, 50, 100]:
        result = benchmark_vault_workflow("test_password", size_mb)
        print(f"{result['data_size_mb']} МБ"
              f"  {result['kdf_ms']}ms"
              f"  {result['encrypt_ms']}ms"
              f"  {result['decrypt_ms']}ms"
              f"  {result['total_ms']}ms"
              f"  {result['throughput_mbps']} МБ/с")
```

## Устранение неполадок

### Ошибка: `cryptography` не установлена

**Причина**: отсутствует зависимость для низкоуровневых криптографических операций.

```bash
pip install cryptography
# Или через ansible
pip install ansible-core[crypto]
```

### Ошибка: `Unsupported algorithm` при расшифровке

**Причина**: файл зашифрован нестандартным алгоритмом (не AES-256-CTR) или поврежден.

```bash
# Проверка заголовка
head -1 secrets.yml
# Должен быть: $ANSIBLE_VAULT;1.1;AES256 или $ANSIBLE_VAULT;1.2;AES256

# Если заголовок отсутствует — файл не является Vault-файлом
```

### Ошибка: `Invalid token` при проверке HMAC

**Причина**: данные файла были модифицированы после шифрования.

```bash
# Восстановление из Git
git checkout HEAD -- secrets.yml

# Или перешифровка с тем же паролем
ansible-vault encrypt --vault-id prod@prompt secrets.yml
```

### Ошибка: `PBKDF2 iteration count too low` (предупреждение)

**Причина**: версия Ansible или `cryptography` считает 10 000 итераций недостаточными.

```bash
# Проверка текущего числа итераций
python3 -c "
import hashlib, os
salt = os.urandom(32)
dk = hashlib.pbkdf2_hmac('sha256', b'password', salt, 10000)
print(f'Итерации: 10000 (рекомендуется >= 600000)')
print(f'Длина ключа: {len(dk)} байт')
"
```

### Ошибка: `Memory error` при работе с большими файлами

**Причина**: зашифрованный файл слишком велик для обработки в памяти.

```bash
# Постепенная обработка (encrypt_string вместо encrypt)
ansible-vault encrypt_string "$(cat large_secret.txt)" --name 'large_secret'

# Или разбиение файла на части
split -b 1M large_vault.yml large_vault_part_
```

## Граничные случаи и ограничения

- **Максимальный размер файла**: теоретических ограничений нет, но для файлов >100 МБ рекомендуется использование `encrypt_string` или разбиение.
- **Длина пароля**: нет верхнего ограничения; PBKDF2 обработает пароль любой длины, но рекомендуется 16+ символов.
- **Число Vault ID**: нет технических ограничений; на практике >10 Vault ID замедляют расшифровку при версии 1.1.
- **Производительность KDF**: 10 000 итераций PBKDF2 занимают ~50-100 мс на современном CPU; для Raspberry Pi может потребоваться ~300 мс.
- **Параллельные расшифрования**: при одновременном запуске нескольких плейбуков каждый процесс выполняет свою деривацию ключа; общих ресурсов не разделяется.
- **Кроссплатформенность**: зашифрованные файлы совместимы между Linux, macOS и Windows (с Python и ansible-core).
- **Соль (Salt)**: генерируется случайно при каждом шифровании; одинаковые пароли дают разные ключи для разных файлов.
- **Версия формата 1.1**: не поддерживает Vault ID; при использовании нескольких хранилищ Ansible перебирает все ключи последовательно.

## Справочник переменных окружения

| Переменная | Описание | Влияние на алгоритмы |
|------------|----------|----------------------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу/скрипту с паролем | Не влияет на алгоритмы; определяет только источник ключа |
| `ANSIBLE_VAULT_IDentities` | Список Vault ID через запятую | Влияет на выбор ключа (формат 1.2); для 1.1 — порядок перебора |
| `PYTHONPATH` | Путь к модулям Python | Может потребоваться для нестандартных криптографических библиотек |
| `CRYPTOGRAPHY_OPENSSL_NO_LEGACY` | Отключение legacy-алгоритмов OpenSSL | Влияет на доступные алгоритмы (не рекомендуется менять) |
| `ANSIBLE_VAULT_ENCRYPT_identity` | Vault ID для шифрования по умолчанию | Определяет метку в заголовке формата 1.2 |

## Дополнительная информация

### Связанные темы
- [Ansible Vault: Основы](./basics.md) — базовые команды и начало работы.
- [Управление паролями и источниками](./passwords.md) — детали работы с клиентскими скриптами и CLI.

### Углубленные руководства
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — работа с иерархией Vault ID.
- [Лучшие практики по безопасности](./best_practices.md) — рекомендации по защите секретов в Git и логах.
- [Практические примеры использования](./examples.md) — реальные сценарии применения в инфраструктуре.
