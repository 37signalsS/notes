# ГОСТ-криптография — реализация в Linux/DevOps

## Определения

**ГОСТ** — государственный стандарт Российской Федерации на криптографические алгоритмы. Основные стандарты:
- **ГОСТ Р 34.12-2015** — симметричное шифрование (Кузнечик, Магма)
- **ГОСТ Р 34.13-2015** — режимы работы блочных шифров (CTR, CTC, CBC)
- **ГОСТ Р 34.10-2012** — электронная подпись (ECDSA аналог на кривых ГОСТ)
- **ГОСТ Р 34.11-2012** — хэширование (Stribog, аналог SHA-256/512)
- **ГОСТ Р 34.11-2018** — HMAC на базе Stribog

**Кузнечик** — блочный шифр с длиной блока 128 бит и ключом 256 бит. Рекомендуется для зашифрования информации до «секретно» включительно.

**Магма** — блочный шифр с длиной блока 64 бита и ключом 256 бит. Для информации до «секретно» включительно.

**Stribog (ГОСТ Р 34.11-2012)** — функция хэширования, выдающая результат 256 или 512 бит. Аналог SHA-256/SHA-512.

**СКЗИ (Средство криптографической защиты информации)** — средство, реализующее ГОСТ-алгоритмы и сертифицированное ФСБ/ФСТЭК.

**CryptoPro** — коммерческая реализация ГОСТ-криптографии для Windows/Linux. Самый распространённый СКЗИ в российских госструктурах.

**openSSL с ГОСТ** — OpenSSL с патчами поддержки ГОСТ-алгоритмов (через engine или provider).

---

## Теоретический блок

### Когда нужна ГОСТ-криптография

| Сценарий | Обязательность | Инструменты |
| :--- | :--- | :--- |
| Государственные органы | Обязательно (ФСБ/ФСТЭК) | CryptoPro, VIAZ |
| Финансовый сектор (Банк России) | Рекомендуется | CryptoPro, OpenSSL+ГОСТ |
| Медицинские учреждения | Рекомендуется (ФЗ-152) | CryptoPro |
| Телекоммуникации | Опционально | OpenSSL+ГОСТ |
| Частный сектор (без госконтрактов) | Не обязательно | OpenSSL (для совместимости) |

### Алгоритмы ГОСТ vs международные

| Функция | ГОСТ | Международный аналог |
| :--- | :--- | :--- |
| Симметричное шифрование | Кузнечик (128/256) | AES-256 |
| Хэширование | Stribog-256/512 | SHA-256/SHA-512 |
| ЭЦП | ГОСТ Р 34.10-2012 | ECDSA (P-256/P-384) |
| HMAC | ГОСТ Р 34.11-2018 | HMAC-SHA256 |
| RSA | ГОСТ Р 34.10-2012 (EC) | RSA-2048/4096 |

### OpenSSL 3.0+ и ГОСТ

OpenSSL 3.0+ поддерживает ГОСТ через mechanism **providers** (вместо старого `engine`):

```
┌────────────────────┐
│   OpenSSL 3.0+     │
│                    │
│  ┌──────────────┐  │
│  │ Default      │  │  RSA, ECDSA, AES, SHA-256
│  │ Provider     │  │
│  └──────────────┘  │
│  ┌──────────────┐  │
│  │ GOST         │  │  Кузнечик, Stribog, ГОСТ ECDSA
│  │ Provider     │  │
│  └──────────────┘  │
│  ┌──────────────┐  │
│  │ Legacy       │  │  DES, RC4, MD5
│  │ Provider     │  │
│  └──────────────┘  │
└────────────────────┘
```

---

## Практический блок

### Установка OpenSSL с поддержкой ГОСТ

#### Ubuntu/Debian

```bash
# Установка пакета с поддержкой ГОСТ
sudo apt install libengine-gost-openssl1.1
# Или для OpenSSL 3.0+:
sudo apt install gost-engine

# Проверка доступности engine
openssl engine -t gost
# → (gost) GOST engine support
# → [ OK ]
```

#### RHEL/CentOS/Fedora

```bash
# CentOS 8 / Fedora
sudo dnf install openssl-gost-engine

# Проверка
openssl engine -t gost
```

#### Сборка из исходников (рекомендуется для production)

```bash
# Клонирование gost-engine
git clone https://github.com/gost-engine/engine.git
cd engine

# Сборка для OpenSSL 3.0+
mkdir build && cd build
cmake .. \
  -DCMAKE_BUILD_TYPE=Release \
  -DOPENSSL_ROOT_DIR=/usr/local/ssl
make -j$(nproc)
sudo make install

# Конфигурация OpenSSL для использования GOST engine
cat >> /etc/ssl/openssl.cnf << 'EOF'
openssl_conf = openssl_def

[openssl_def]
engines = engine_section

[engine_section]
gost = gost_section

[gost_section]
engine_id = gost
dynamic_path = /usr/lib/x86_64-linux-gnu/engines-3/gost.so
default_algorithms = ALL
EOF

# Проверка
openssl engine -t gost
```

### Генерация ключей ГОСТ

```bash
# Генерация ключевой пары ГОСТ Р 34.10-2012 (256 бит)
openssl genpkey -algorithm gost2012_256 \
  -pkeyopt paramset:A \
  -out gost_key.pem

# Генерация ключа ГОСТ Р 34.10-2012 (512 бит)
openssl genpkey -algorithm gost2012_512 \
  -pkeyopt paramset:A \
  -out gost_key_512.pem

# Просмотр ключа
openssl pkey -in gost_key.pem -text -noout
# → ASN1 OID: GOST R 34.10-2012 256 bit
# → Parameter set: A
```

### Создание CSR с ГОСТ

```bash
# CSR с алгоритмом подписи ГОСТ
openssl req -new -key gost_key.pem \
  -pkeyopt paramset:A \
  -subj "/C=RU/ST=Moscow/O=MyOrg/CN=gost-service.internal" \
  -out gost.csr

# Просмотр CSR
openssl req -in gost.csr -text -noout | grep "Signature Algorithm"
# → Signature Algorithm: gost2012_256
```

### Подписание сертификата ГОСТ

```bash
# Создание конфигурации для ГОСТ-расширений
cat > gost_ext.cnf << 'EOF'
[req]
distinguished_name = req_dn
req_extensions = v3_req

[req_dn]
C = RU
ST = Moscow
O = MyOrg
CN = GOST Root CA

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash

[v3_req]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
subjectKeyIdentifier = hash
EOF

# Самоподписанный сертификат Root CA с ГОСТ
openssl req -new -x509 -key gost_key.pem \
  -pkeyopt paramset:A \
  -config gost_ext.cnf \
  -extensions v3_ca \
  -days 3650 \
  -out gost_ca.crt

# Проверка
openssl x509 -in gost_ca.crt -text -noout | grep "Signature Algorithm"
# → Signature Algorithm: gost2012_256
```

### Шифрование с использованием Кузнечика

```bash
# Зашифрование файла Кузнечиком (ГОСТ Р 34.12-2015)
openssl enc -kuznyechik -salt -pbkdf2 \
  -in plaintext.txt \
  -out encrypted.bin

# Расшифрование
openssl enc -d -kuznyechik -salt -pbkdf2 \
  -in encrypted.bin \
  -out decrypted.txt

# Проверка
diff plaintext.txt decrypted.txt
# → нет вывода = файлы идентичны
```

### Хэширование Stribog

```bash
# Вычисление Stribog-256
openssl dgst -md_gost12_256 plaintext.txt
# → (stdin)= abc123...

# Вычисление Stribog-512
openssl dgst -md_gost12_512 plaintext.txt
# → (stdin)= def456...

# HMAC на базе Stribog
openssl dgst -md_gost12_256 -hmac "secret_key" plaintext.txt
```

### Интеграция с Nginx (HTTPS на ГОСТ)

```nginx
server {
    listen 443 ssl;
    server_name gost-service.internal;

    ssl_certificate     /etc/ssl/certs/gost-service.crt;  # подписанный ГОСТ
    ssl_certificate_key /etc/ssl/private/gost-service.key;

    # Поддержка ГОСТ-шифрования в TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'GOST2012-GOST89-GOST89:eNULL';

    # Для совместимости с не-ГОСТ клиентами:
    ssl_ciphers 'HIGH:!aNULL:!MD5';
}
```

### Проверка ГОСТ в OpenSSL

```bash
# Список поддерживаемых алгоритмов
openssl list -public-key-algorithms | grep gost
# → gost2012_256
# → gost2012_512

openssl list -cipher-algorithms | grep -i kuzn
# → KUZNYECHIK

openssl list -digest-algorithms | grep -i gost
# → GOST12-256
# → GOST12-512
```

### CryptoPro CSP (коммерческая реализация)

```bash
# Установка CryptoPro CSP (требуется лицензия)
# Скачивание с cryptopro.ru

# Установка
tar -xzf linux-amd64_deb.tgz
cd linux-amd64_deb
sudo ./install.sh

# Проверка
cpconfig -hardware
# → показывает доступные криптопроцессоры

# Генерация ключа
certmgr -srv -ca -cont -sol -create -prov -name "КриптоПро CSP" \
  -OID 1.2.643.7.1.1.1.1 \
  -pin 12345678

# Просмотр контейнера
certmgr -list -store -cert --thumbprint <thumbprint>
```

### Автоматизация через Ansible

```yaml
- name: Install GOST engine
  hosts: gost_servers
  tasks:
    - name: Install GOST engine package
      apt:
        name: gost-engine
        state: present
      when: ansible_os_family == "Debian"

    - name: Configure OpenSSL for GOST
      lineinfile:
        path: /etc/ssl/openssl.cnf
        line: "{{ item }}"
      loop:
        - "openssl_conf = openssl_def"
        - "[engine_section]"
        - "gost = gost_section"
      notify: restart services

    - name: Generate GOST key
      command: >
        openssl genpkey -algorithm gost2012_256
        -pkeyopt paramset:A
        -out /etc/ssl/private/gost.key
      args:
        creates: /etc/ssl/private/gost.key
```

---

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `engine "gost" not found` | GOST engine не установлен или не сконфигурирован | Установите `gost-engine`, добавьте конфигурацию в `openssl.cnf` |
| `unsupported algorithm: gost2012_256` | OpenSSL собран без поддержки ГОСТ | Используйте дистрибутив с ГОСТ-патчем или соберите из исходников |
| `unable to load engine` | Неправильный путь к .so файлу | Проверьте `dynamic_path` в `openssl.cnf`; `find / -name "gost.so"` |
| `wrong parameter set` | Несовпадение paramset между ключом и подписанием | Используйте одинаковый `-pkeyopt paramset:A` для генерации и подписания |
| `no shared cipher` | Клиент не поддерживает ГОСТ-шифры | Добавьте не-ГОСТ шифры в `ssl_ciphers` для совместимости |

---

## Лучшие практики

1. **Используйте OpenSSL 3.0+ с GOST provider** — более стабильная архитектура, чем старый engine
2. **Для production с госзаказами:** CryptoPro CSP сертифицирован ФСБ; OpenSSL+ГОСТ — для dev/test
3. **Комбинируйте ГОСТ с международными алгоритмами** для совместимости с внешними системами
4. **Регулярно обновляйте** gost-engine — исправления уязвимостей публикуются regularly
5. **Тестируйте** ГОСТ-конфигурацию перед развёртыванием в production
6. **Документируйте** какие сервисы используют ГОСТ, а какие — стандартные алгоритмы

---

## Дополнительная информация

- **ГОСТ Р 34.12-2015** — [Блочный шифр "Кузнечик"](https://gost.ru/)
- **ГОСТ Р 34.10-2012** — [Электронная подпись](https://gost.ru/)
- **[gost-engine](https://github.com/gost-engine/engine)** — OpenSSL engine для ГОСТ
- **[CryptoPro CSP](https://cryptopro.ru/products/csp)** — коммерческая реализация
- **[OpenSSL Providers](https://www.openssl.org/docs/man3.0/man7/migration_guide.html)** — миграция engine → provider
- **[Обзор PKI](../Concepts/pki_overview.md)** — использование ГОСТ в PKI
