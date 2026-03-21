# Диагностика и troubleshooting BIND

## Определения

**named-checkconf** — утилита проверки синтаксиса конфигурационных файлов BIND.

**named-checkzone** — утилита проверки корректности файлов зон.

**rndc** — утилита удалённого управления демоном BIND.

## Базовые концепции

### Уровни диагностики

| Уровень | Инструменты | Назначение |
|---------|-------------|------------|
| **Конфигурация** | `named-checkconf`, `named-checkzone` | Проверка синтаксиса |
| **Служба** | `systemctl status bind9`, `journalctl` | Статус службы, логи |
| **Сеть** | `ss`, `netstat`, `tcpdump` | Порты, трафик |
| **Разрешение** | `dig`, `nslookup`, `host` | Тестирование запросов |
| **Управление** | `rndc` | Перезагрузка, кэш, статистика |

### Типовые коды ошибок DNS

| Код | Описание | Причина |
|-----|----------|---------|
| `NOERROR` | Успешный запрос | — |
| `NXDOMAIN` | Домен не существует | Ошибка в имени или домен не зарегистрирован |
| `SERVFAIL` | Ошибка сервера | Проблема на стороне DNS-сервера |
| `REFUSED` | Запрос отклонён | Блокировка ACL, firewall |
| `FORMERR` | Ошибка формата запроса | Повреждённый пакет |

## Практические сценарии

### 1. Проверка конфигурации

**Перед перезапуском BIND:**

```bash
# Проверка основных конфигов
sudo named-checkconf

# Проверка всех зон
sudo named-checkzone example.com /etc/bind/zones/db.example.com
```

**Ожидаемый вывод:**

```
zone example.com/IN: loaded serial 5
OK
```

**Возможные ошибки:**

```
zone example.com/IN: loading master file: permission denied
→ Проверить права: chown bind:bind /etc/bind/zones/*
```

### 2. Диагностика службы

**Проверка статуса:**

```bash
systemctl status bind9
journalctl -u bind9 -n 50  # последние 50 записей
```

**Типовые проблемы:**

| Симптом | Причина | Решение |
|---------|---------|---------|
| `failed to start` | Ошибка синтаксиса | `named-checkconf` |
| `listening on IPv6` | BIND не слушает IPv4 | Проверить `listen-on` |
| `no TTL specified` | Отсутствие $TTL в зоне | Добавить в файл зоны |
| `permission denied` | Права на файлы | `chown bind:bind` |

### 3. Проверка сетевых портов

**Прослушиваемые порты:**

```bash
# UDP и TCP порт 53
ss -tlnp | grep :53
ss -ulnp | grep :53
```

**Ожидаемый результат:**

```
UDP:  *.53   users:(("named",pid=1234,fd=100))
TCP:  *.53   users:(("named",pid=1234,fd=101))
```

**Если порты не открыты:**

- Проверить `listen-on` в `named.conf.options`
- Проверить брандмауэр: `ufw status` или `firewall-cmd --list-all`

### 4. Тестирование разрешения

**Базовые тесты:**

```bash
# Локальный запрос
dig @127.0.0.1 example.com

# Запрос к конкретному интерфейсу
dig @172.16.0.5 example.com

# Проверка авторитетности
dig @172.16.0.5 example.com SOA

# Обратная зона
dig -x 172.16.0.5
```

**Анализ вывода dig:**

```
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 12345
;; flags: qr aa rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 1, ADDITIONAL: 1

;; QUESTION SECTION:
;example.com.    IN    A

;; ANSWER SECTION:
example.com.    604800    IN    A    192.168.1.10
```

**Флаги:**

- `qr` (Query Response) — это ответ
- `aa` (Authoritative Answer) — авторитетный ответ
- `rd` (Recursion Desired) — запрошена рекурсия
- `ra` (Recursion Available) — рекурсия доступна

### 5. Диагностика трансфера зоны

**Проверка AXFR:**

```bash
# Полный трансфер зоны (если разрешён)
dig @master-server example.com AXFR

# Проверка SOA на синхронизацию
dig @master example.com SOA
dig @slave example.com SOA
# Serial должен совпадать
```

**Проблемы:**

- `transfer failed` — проверить `allow-transfer` на Master
- `connection refused` — брандмауэр блокирует TCP/53
- `serial mismatch` — Slave не обновился, проверить логи

### 6. Логирование и отладка

**Включение логирования запросов:**

```bash
# Временно включить
sudo rndc querylog on

# Проверить логи
tail -f /var/log/named/query.log

# Выключить
sudo rndc querylog off
```

**Уровень отладки:**

```bash
# Включить отладку (уровень 1-9)
sudo rndc trace 5

# Выключить
sudo rndc notrace
```

### 7. Управление кэшем

```bash
# Очистка кэша
sudo rndc flush

# Статистика кэша
sudo rndc status

# Перезагрузка зон без обрыва соединений
sudo rndc reload

# Перезагрузка конкретной зоны
sudo rndc reload example.com
```

### 8. Проверка DNSSEC

```bash
# Проверка подписи зоны
dig @server example.com DNSKEY

# Проверка цепочки доверия
delv example.com

# Статус валидации
dig +dnssec example.com
```

## Дополнительная информация

- **Логи BIND:** `/var/log/syslog`, `/var/log/named/`, `journalctl -u bind9`
- **Утилиты:** `named-checkconf`, `named-checkzone`, `dig`, `rndc`, `delv`
- **Безопасность:**
  - **CVE-2025-13878:** Уязвимость в обработке BRID/HHIT записей — удалённый crash сервера (CVSS 7.5)
  - Исправлена в BIND 9.18.44, 9.20.18, 9.21.17 (January 2026)
  - Рекомендуется обновить как можно скорее
- **Сопутствующие заметки:**
  - [Диагностика DNS](../../../Diagnostics/Networking/dns/overview.md) — общие инструменты
  - [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md) — DNSSEC
  - [Настройка Master](./master_server_local_zone.md) — первичный сервер
