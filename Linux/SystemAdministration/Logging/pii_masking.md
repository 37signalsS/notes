# Маскирование PII и секретов в логах

## Определения

**Маскирование (masking/redaction)** — процесс скрытия или замены чувствительных данных (персональные идентифицирующие данные — PII, пароли, API-ключи, номера карт) в логах до их записи или отправки в централизованное хранилище. Критически важно для соответствия регуляторным требованиям (PCI DSS, GDPR, ФЗ-152) и предотвращения утечек.

**Классификация чувствительных данных:**

| Тип | Примеры | Регулятор |
|:---|:---|:---|
| **PII** | ФИО, email, телефон, паспорт, ИНН | GDPR, ФЗ-152 |
| **Финансовые** | Номера карт (PAN), CVV, PIN | PCI DSS |
| **Аутентификация** | Пароли, токены, API-ключи, сертификаты | CIS, NIST |
| **Инфраструктурные** | IP-адреса внутренних сетей, DNS-имена | Стандарты безопасности |
| **Медицинские** | Номера полисов, диагнозы | HIPAA |

**Принцип:** маскирование выполняется **как можно раньше** в pipeline (на агенте или до записи в лог), чтобы чувствительные данные никогда не покидали хост-источник в открытом виде.

## Базовые концепции

### Уровни маскирования

| Уровень | Где выполняется | Плюсы | Минусы |
|:---|:---|:---|:---|
| **Приложении** | Код приложения | Максимальная точность | Требует изменений в коде |
| **Агенте** | Vector, Fluent Bit, rsyslog | Без изменений в коде | Regex может пропустить формат |
| **Хранилище** | Elasticsearch, Loki | Централизованная политика | Данные уже прошли по сети |
| **На лету (query time)** | Kibana, Grafana | Гибкость | Данные хранятся в открытом виде |

**Рекомендация:** комбинируйте уровни — базовое маскирование на агенте + дополнительные правила в хранилище.

### Методы маскирования

| Метод | Описание | Пример |
|:---|:---|:---|
| **Замена на звездочки** | Частичное скрытие | `4111-1111-1111-1111` → `****-****-****-1111` |
| **Хэширование** | Необратимое преобразование | `user@example.com` → `a1b2c3d4e5` |
| **Обрезка** | Удаление suffixed данных | `Bearer eyJhb...` → `[REDACTED]` |
| **Маска по regex** | Поиск по паттерну | `password=.*` → `password=***` |
| **Структурированная замена** | Замена на валидный, но фиктивный токен | `1234-5678-9012-3456` → `XXXX-XXXX-XXXX-3456` |

## Практические сценарии

### Сценарий 1: Vector (Rust) — redact-процессор

Vector имеет встроенный процессор `redact` для маскирования PII:

```yaml
# /etc/vector/vector.yaml
transforms:
  mask_pii:
    type: redact
    inputs:
      - syslog
    mode: "regex"
    patterns:
      # Nomerа kart (PAN)
      - '\b(?:\d[ -]*?){13,16}\b'
      # Email
      - '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
      # Telefony
      - '\b\+?[1-9]\d{1,14}\b'
      # API-keys
      - '(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+'
      # SSN (US)
      - '\b\d{3}-\d{2}-\d{4}\b'
    replace: "[REDACTED]"
    # Zachitit' ot obreza
    truncatable: false
```

**Пример VRL для slozhnoy logiki:**

```vrl
# Transformatsiya logov s redact
.message = redact(.message, 
    patterns: [
        r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',  # PAN
        r'(?i)(password|secret|token|key)\s*[=:]\s*\S+',   # Secrets
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'  # Email
    ],
    redact: "[REDACTED]"
)
```

### Сценарий 2: Fluent Bit — parser + filter

```ini
# /etc/fluent-bit/parsers.conf
[PARSER]
    Name        mask_pii
    Format      regex
    Regex       ^(?P<timestamp>.*) (?P<level>.*) (?P<message>.*)$
    # PII maskirovanie cherez rewrite
```

```ini
# /etc/fluent-bit/fluent-bit.conf
[FILTER]
    Name          rewrite
    Match         *
    # Zamenyaem PAN
    Rule          (\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}) ** [CARD_REDACTED]
    # Zamenyaem email
    Rule          ([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}) ** [EMAIL_REDACTED]
    # Zamenyaem parolei
    Rule          ((?i)(password|passwd|pwd)\s*[=:]\s*)\S+ $1[REDACTED]
    # Zamenyaem API key
    Rule          ((?i)(api[_-]?key|token|secret)\s*[=:]\s*)\S+ $1[REDACTED]
```

### Сценарий 3: rsyslog — mmnormalize +蔽

```conf
# /etc/rsyslog.d/50-pii-masking.conf

# Zagruzka modulya
module(load="mmnormalize")

# Pravilo dlya PAN (Visa/Mastercard)
template(name="masked_log" type="string"
    string="%msg:R,ERE,1:([0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4})--end:0:****-****-****-%1%2%3%4%\n")

# Zamenyaem v logakh
if $msg contains "password=" then {
    action(type="mmnormalize"
           rulebase="/etc/rsyslog.d/pii.rulebase")
}
```

### Сценарий 4: syslog-ng — mask()

```conf
# /etc/syslog-ng/conf.d/pii-masking.conf

# Pravilo maskirovaniya
parser p_mask_pii {
    mask(
        # PAN
        mask-char("*")
        seeds(
            "\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}"
        )
    );
};

# Pravilo dlya email
parser p_mask_email {
    mask(
        mask-char("*")
        seeds(
            "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        )
    );
};

# Pravilo dlya secrets
parser p_mask_secrets {
    rewrite(
        subst("password=\\S+", "password=[REDACTED]")
        subst("(?i)(token|key|secret)=\\S+", "$1=[REDACTED]")
    );
};

log {
    source(s_local);
    parser(p_mask_pii);
    parser(p_mask_email);
    parser(p_mask_secrets);
    destination(d_central);
};
```

### Сценарий 5: Паттерны для типовых форматов

```yaml
# Universal'nye regex patterny dlya PII

patterns:
  # PCI DSS: PAN (Visa, Mastercard, Amex, etc.)
  pan:
    - '\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12}|(?:2131|1800|35\d{3})\d{11})\b'

  # Email
  email: '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

  # Telefon (mezhdunarodnyy format)
  phone: '\b\+?[1-9]\d{1,14}\b'

  # SSN (US)
  ssn: '\b\d{3}-\d{2}-\d{4}\b'

  # Passport RF
  passport_rf: '\b\d{2}\s?\d{2}\s?\d{6}\b'

  # INN (RF)
  inn_rf: '\b\d{10}(\d{2})?\b'

  # API-keys (rasprostranennye formaty)
  api_keys:
    - '(?i)(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}'  # GitHub
    - '(?i)AKIA[0-9A-Z]{16}'                              # AWS Access Key
    - '(?i)(?:sk_live|pk_live)_[0-9a-zA-Z]{24,}'           # Stripe
    - '(?i)xox[bpsar]-[0-9a-zA-Z-]+'                       # Slack
    - '(?i)eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_.+/=]+'  # JWT

  # IPv4 (vnutrennie seti)
  private_ipv4: '(?:(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3})'
```

### Сценарий 6: PostgreSQL — анонимизация для Dev/Staging

```sql
-- Anonimizatsiya PII pri vygruzke v testovuyu sredu
CREATE OR REPLACE FUNCTION mask_email(email TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN regexp_replace(email, 
        '([a-zA-Z0-9])[a-zA-Z0-9._%+-]*@', 
        '\1***@');
END;
$$ LANGUAGE plpgsql;

-- Ispol'zovanie
SELECT 
    id,
    mask_email(email) AS email,
    '****' || right(phone, 4) AS phone,
    'USER_' || id AS name
FROM users;
```

### Сценарий 7: Мониторинг утечек PII

```bash
#!/bin/bash
# /usr/local/bin/check-pii-leaks.sh
# Proverka logov na nalicie PII

LOG_DIR="/var/log/app"
PII_PATTERNS=(
    '\b[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}\b'  # PAN
    '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'      # Email
    '(?i)(password|passwd|pwd)\s*[=:]\s*\S+'                      # Passwords
    '(?i)(api[_-]?key|token|secret)\s*[=:]\s*\S+'                 # API keys
)

echo "Проверка на утечки PII в логах..."

for pattern in "${PII_PATTERNS[@]}"; do
    matches=$(grep -rPn "$pattern" "$LOG_DIR" 2>/dev/null | wc -l)
    if [ "$matches" -gt 0 ]; then
        echo "ALERT: Найдено $matches совпадений по паттерну: $pattern"
    fi
done
```

## Соответствие стандартам

### PCI DSS v4.0

| Требование | Описание | Реализация |
|:---|:---|:---|
| **3.4** | PAN должен быть нечитаем при хранении | Замена на `*` или хэширование (SHA-256) |
| **3.5** | Криптографическое управление ключами | Шифрование at rest для логов с PAN |
| **10.3** | Логи не должны содержать PAN в открытом виде | Маскирование до записи |

### GDPR

| Статья | Требование | Реализация |
|:---|:---|:---|
| **Art. 5(1)(c)** | Минимизация данных | Не логировать PII без необходимости |
| **Art. 17** | Право на удаление | Удаление из логов при запросе (erasure) |
| **Art. 25** | Privacy by Design | Маскирование по умолчанию в конфигурации |

### ФЗ-152

| Требование | Реализация |
|:---|:---|
| **Локализация** | Логи с ПДн хранятся на территории РФ |
| **Защита** | Шифрование at rest + access control |
| **Аудит** | Журналирование доступа к логам с ПДн |

## Диагностика

### Проверка наличия PII в логах

```bash
# Поиск PAN в логах
sudo grep -rPn '\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})\b' /var/log/

# Поиск email
sudo grep -rPn '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}' /var/log/app/

# Поиск паролей
sudo grep -rPn '(?i)(password|passwd|pwd)\s*[=:]\s*\S+' /var/log/

# Быстрая проверка через aggr
sudo grep -rPn '(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*\S+' /var/log/ | \
    awk -F: '{print $1}' | sort -u
```

## Дополнительная информация

### Лучшие практики

1. **Маскируйте на агенте** — до отправки в сеть. Данные не должны покидать хост в открытом виде.
2. **Используйте replacement tokens** — `****-****-****-1111` вместо простого удаления (сохраняет структуру для анализа).
3. **Не маскируйте всё подряд** — слишком агрессивное маскирование убивает ценность логов.
4. **Тестируйте regex** — ложные срабатывания (false positives) могут сломать парсинг.
5. **Включите аудит маскирования** — логируйте факт маскирования (но не само значение).
6. **Для JSON-логов** — маскируйте конкретные поля, а не весь текст.
7. **Периодически сканируйте** логи на наличие PII (автоматизированные проверки).
8. **Документируйте политику** — какие данные маскируются, какие хранятся в открытом виде.
9. **Используйте structured logging** — маскирование полей проще в JSON, чем в plain text.
10. **Интегрируйте в CI/CD** — статический анализ кода на наличие логирования секретов (gitleaks, truffleHog).

### См. также

- [Обзор системы логирования](./logging_overview.md)
- [Централизованное логирование](./cloud_logging.md)
- [Vector: VRL Language](../../../Vector/vrl_language.md)
