# Настройка вторичного DNS-сервера (Slave)

## Определения

**Slave-сервер (Secondary)** — авторитативный DNS-сервер, автоматически копирующий зону с Master-сервера через трансфер зоны (AXFR/IXFR).

**Трансфер зоны** — процесс копирования данных зоны между серверами (полный AXFR или инкрементальный IXFR).

## Базовые концепции

### Механизм синхронизации

| Этап | Описание |
|------|----------|
| 1 | Secondary запрашивает SOA-запись у Master |
| 2 | Сравнивает серийный номер с локальным |
| 3 | Если Serial > локального → запрос AXFR/IXFR |
| 4 | Зона обновляется и сохраняется в файл |

### Преимущества Master/Slave архитектуры

- **Отказоустойчивость:** При падении Master Slave продолжает отвечать на запросы
- **Распределение нагрузки:** Запросы клиентов распределяются между серверами
- **Географическое распределение:** Slave в другом дата-центре повышает доступность

## Практические сценарии

### 1. Настройка Slave-сервера

**Установка BIND:**

```bash
sudo apt-get update
sudo apt-get install -y bind9 dnsutils
```

**Конфигурация зоны в `/etc/bind/named.conf.local`:**

```conf
zone "test.example.com" {
    type slave;
    file "/var/lib/bind/test.example.com.zone";  // Путь для локальной копии
    masters { 172.16.0.5; };  // IP Master-сервера
};
```

**Создание директории для файлов зон:**

```bash
sudo mkdir -p /var/lib/bind
sudo chown bind:bind /var/lib/bind
```

**Перезапуск и проверка:**

```bash
sudo systemctl restart bind9

# Проверка логов на наличие ошибок
journalctl -u bind9 -f

# Проверка файла зоны (должен появиться после успешного трансфера)
ls -la /var/lib/bind/
```

### 2. Настройка Master для разрешения трансфера

**На Master-сервере в `/etc/bind/named.conf.local`:**

```conf
zone "test.example.com" {
    type master;
    file "/etc/bind/zones/db.test.example.com";
    allow-transfer { 172.16.0.6; };  // IP Slave-сервера
    also-notify { 172.16.0.6; };     // Уведомлять Slave об изменениях
};
```

**Параметры:**

- `allow-transfer` — разрешает трансфер зоны только указанным IP
- `also-notify` — отправляет NOTIFY-сообщения Slave при изменении зоны

### 3. Проверка синхронизации

**На Slave-сервере:**

```bash
# Проверка статуса зоны
dig @localhost test.example.com SOA

# Проверка файла зоны
cat /var/lib/bind/test.example.com.zone

# Проверка логов
grep "transfer" /var/log/syslog
```

**Ожидаемый результат:**

```
test.example.com.  604800  IN  SOA  ns1.test.example.com. admin.test.example.com. (
    2  ; Serial (должен совпадать с Master)
    ...
)
```

### 4. Диагностика проблем

**Проблема: трансфер не выполняется**

```bash
# Проверка доступности Master
dig @172.16.0.5 test.example.com AXFR

# Проверка логов на Slave
journalctl -u bind9 | grep -i error

# Проверка прав на файл зоны
ls -la /var/lib/bind/
```

**Возможные причины:**

- `allow-transfer` не настроен на Master
- Брандмауэр блокирует TCP/53 (AXFR использует TCP)
- Неправильный путь к файлу зоны

## Дополнительная информация

- **AXFR:** Полный трансфер зоны (TCP/53)
- **IXFR:** Инкрементальный трансфер (только изменения)
- **NOTIFY:** Механизм уведомления Slave об изменениях (RFC 1996)
- **Сопутствующие заметки BIND:**
  - [Настройка Master](./master_server_local_zone.md) — первичный сервер
  - [Обратная зона](./reverse_zone_configuration.md) — PTR-записи для Slave
  - [Тoubleshooting](./troubleshooting.md) — диагностика трансфера
  - [Зоны DNS](../../../../Networking/Protocols/DNS/dns_zones.md) — теория зон
