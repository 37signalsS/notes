# LDAP: Анализ трафика (tcpdump / Wireshark)

## Определения

**tcpdump** — утилита командной строки для захвата и анализа сетевого трафика. Позволяет фильтровать пакеты по протоколу, порту, IP и другим критериям.

**Wireshark** — графический анализатор сетевых протоколов с поддержкой декодирования LDAP/ASN.1. Позволяет детально исследовать содержимое LDAP-запросов и ответов.

**LDAP Bind Request** — первый пакет в сессии LDAP, содержащий DN и пароль (или SASL-механизм) для аутентификации клиента.

**LDAP Search Request** — пакет с фильтром поиска, Base DN, scope и запрашиваемыми атрибутами.

**BER/DER (Basic/Distinguished Encoding Rules)** — формат кодирования ASN.1, используемый LDAP для передачи данных в сетевом потоке.

**StartTLS** — расширение LDAP, позволяющее установить TLS-соединение поверх незашифрованного порта 389. Видно в трафике как Extended Request с OID 1.3.6.1.4.1.1466.20037.

**SASL (Simple Authentication and Security Layer)** — фреймворк аутентификации, используемый в LDAP для GSSAPI (Kerberos), DIGEST-MD5 и других механизмов.

---

## Базовые концепции

### Когда нужен анализ трафика

- Диагностика ошибок аутентификации (неверный пароль, SASL failures)
- Поиск проблемы производительности (медленные запросы, таймауты)
- Отладка репликации (конфликты, разрывы соединений)
- Проверка шифрования (убедиться, что LDAPS/StartTLS работает)
- Аудит безопасности (кто и когда обращался к LDAP)

### Структура LDAP-пакета

```text
+------------------+
| Ethernet Header  |
+------------------+
| IP Header        |
+------------------+
| TCP Header       |
+------------------+
| LDAP Message     |
|  +-------------+ |
|  | Message ID  | |
|  +-------------+ |
|  | Protocol Op | |  -- Bind Request / Search Request / etc.
|  +-------------+ |
|  | Controls    | |  -- Paged Results, Proxied Auth, etc.
|  +-------------+ |
+------------------+
```

### Порты и протоколы

| Порт | Протокол | Фильтр tcpdump |
|:---|:---|:---|
| 389 | LDAP (или StartTLS) | `port 389` |
| 636 | LDAPS | `port 636` |
| 3389 | 389DS (стандартный) | `port 3389` |
| 3636 | 389DS LDAPS | `port 3636` |

---

## Практические сценарии

### 1. Захват LDAP-трафика через tcpdump

```bash
# Захват всех LDAP-запросов на порту 389
sudo tcpdump -i eth0 port 389 -nn -vv -w ldap_capture.pcap

# Захват с фильтрацией по IP клиента
sudo tcpdump -i eth0 port 389 and host 10.0.0.50 -nn -w ldap_client.pcap

# Захват LDAPS (порт 636)
sudo tcpdump -i eth0 port 636 -nn -w ldaps_capture.pcap

# Захват с ограничением по времени (60 секунд)
sudo timeout 60 tcpdump -i eth0 port 389 -nn -w ldap_60s.pcap

# Захват с ограничением пакетов (1000 пакетов)
sudo tcpdump -i eth0 port 389 -nn -c 1000 -w ldap_1000.pcap
```

### 2. Анализ LDAP-трафика в реальном времени

```bash
# Вывод DNS-имен вместо IP
sudo tcpdump -i eth0 port 389 -nn -vv

# Вывод в читаемом формате с decoded LDAP
sudo tcpdump -i eth0 port 389 -nn -A

# Только Bind Request (первые 2 байта LDAP = message type 0)
sudo tcpdump -i eth0 port 389 -nn -A | grep -A5 "Bind"

# Подсчет LDAP-сессий
sudo tcpdump -i eth0 port 389 -nn 2>/dev/null | \
  grep "S" | wc -l
```

### 3. Диагностика ошибок аутентификации

```bash
# Захват и поиск Bind Request с ошибками
sudo tcpdump -i eth0 port 389 and host 10.0.0.50 -nn -A 2>/dev/null | \
  grep -E "Bind|Result|error"

# Поиск конкретного DN в трафике
sudo tcpdump -i eth0 port 389 -nn -A 2>/dev/null | \
  grep -i "cn=admin"
```

### 4. Проверка шифрования

```bash
# Проверка, что LDAPS работает (порт 636)
sudo tcpdump -i eth0 port 636 -nn -c 5

# Проверка StartTLS (порт 389 с последующим TLS handshake)
sudo tcpdump -i eth0 port 389 -nn -A 2>/dev/null | \
  grep -i "starttls\|ExtendedRequest"

# Проверка, что нет plaintext паролей в трафике
sudo tcpdump -i eth0 port 389 -nn -A 2>/dev/null | \
  grep -i "simple\|password"
# Если пароли видны = TLS не настроен!
```

### 5. Анализ в Wireshark

```bash
# Конвертация pcap для Wireshark
tcpdump -i eth0 port 389 -nn -w ldap.pcap
# Открыть в Wireshark: File -> Open -> ldap.pcap

# Фильтры Wireshark для LDAP:
# ldap                     -- все LDAP-пакеты
# ldap.opcode == 0         -- Bind Request
# ldap.opcode == 3         -- Search Request
# ldap.opcode == 7         -- Modify Request
# ldap.resultCode != 0     -- Все ошибки
# ldap.authType == simple  -- Simple bind (без шифрования!)
# ldap.authType == sasl    -- SASL bind (Kerberos)
```

### 6. Анализ репликации

```bash
# Захват репликационного трафика между мастерами
sudo tcpdump -i eth0 host ldap-01 and host ldap-02 -nn -w repl.pcap

# Анализ репликационных операций
sudo tcpdump -i eth0 port 389 -nn -A 2>/dev/null | \
  grep -i "replication\|syncrepl\|refresh"
```

### 7. Поиск медленных LDAP-запросов

```bash
# tcpdump с timestamps для анализа задержек
sudo tcpdump -i eth0 port 389 -nn -tttt 2>/dev/null | \
  awk '/Search Request/,/Search Result/'
```

### 8. Анализ через tshark (CLI Wireshark)

```bash
# Установка tshark
sudo apt install tshark -y

# Декодирование LDAP-пакетов
tshark -r ldap.pcap -Y ldap -T fields \
  -e frame.time -e ip.src -e ldap.opcode -e ldap.dn

# Подсчет Bind Request по IP
tshark -r ldap.pcap -Y "ldap.opcode==0" -T fields \
  -e ip.src | sort | uniq -c | sort -rn

# Поиск ошибок
tshark -r ldap.pcap -Y "ldap.resultCode!=0" -T fields \
  -e frame.time -e ip.src -e ldap.resultCode -e ldap.errorMessage
```

## Дополнительная информация

### Безопасность при анализе

```text
[ ] Не захватывайте трафик в production без согласования
[ ] Не публикуйте pcap-файлы (содержат пароли в plaintext)
[ ] Используйте фильтры для сужения захвата
[ ] Удаляйте pcap-файлы после анализа
[ ] В production используйте только LDAPS (порт 636)
```

### Полезные фильтры tcpdump

| Фильтр | Описание |
|:---|:---|
| `port 389` | Все LDAP-пакеты |
| `port 636` | Все LDAPS-пакеты |
| `host 10.0.0.1` | Трафик с/на конкретный IP |
| `src port 389` | Только ответы сервера |
| `dst port 389` | Только запросы клиентов |
| `tcp[tcpflags] & tcp-syn != 0` | Только новые соединения |

### См. также

- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[LDAP Security Hardening](./ldap_security.md)** — настройка безопасности
- **[LDAP мониторинг](./ldap_monitoring.md)** — метрики и алерты
