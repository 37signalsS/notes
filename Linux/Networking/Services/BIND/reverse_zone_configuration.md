# Настройка обратной зоны

## Определения

**Обратная зона (Reverse Zone)** — DNS (Domain Name System — система доменных имён) зона для преобразования IP (Internet Protocol — межсетевой протокол) адресов в доменные имена с помощью PTR-записей.

**PTR (Pointer) запись** — ресурсная запись DNS, указывающая на каноническое имя хоста для данного IP-адреса.

## Базовые концепции

### Формат обратных зон

| Диапазон IP | Формат зоны | Пример |
|-------------|-------------|--------|
| `/24` (Class C) | `X.Y.in-addr.arpa` | `16.172.in-addr.arpa` |
| `/16` (Class B) | `Y.in-addr.arpa` | `172.in-addr.arpa` |
| IPv6 | `...ip6.arpa` | `8.b.d.0.1.0.0.2.ip6.arpa` |

### Особенности PTR-записей

- **Администрирование:** настраиваются владельцем IP-диапазона (провайдер, хостинг-провайдер).
- **Применение:** верификация почты (SPF — Sender Policy Framework), логирование, диагностика.
- **Независимость:** обратная зона логически не зависит от прямой зоны.

## Практические сценарии

### 1. Настройка обратной зоны на Master-сервере

**Объявление зоны в `/etc/bind/named.conf.local`:**

```conf
zone "16.172.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/rev.16.172.in-addr.arpa";
    allow-transfer { 172.16.0.6; };  // IP-адрес Slave-сервера
};
```

### 2. Создание файла обратной зоны

**Файл `/etc/bind/zones/rev.16.172.in-addr.arpa`:**

```dns
$TTL 3600
@   IN  SOA  ns1.test.example.com. admin.test.example.com. (
    1           ; Serial
    3h          ; Refresh
    1h          ; Retry
    1w          ; Expire
    1h )        ; Negative TTL

; NS-записи для зоны
    IN  NS  ns1.test.example.com.
    IN  NS  ns2.test.example.com.

; PTR-записи (последние два октета IP в обратном порядке)
5.0     IN  PTR  ns1.test.example.com.
6.0     IN  PTR  ns2.test.example.com.
101.3   IN  PTR  host.test.example.com.
```

**Разбор записей:**

| Запись | IP-адрес | Доменное имя |
|--------|----------|--------------|
| `5.0` | `172.16.0.5` | `ns1.test.example.com.` |
| `6.0` | `172.16.0.6` | `ns2.test.example.com.` |
| `101.3` | `172.16.3.101` | `host.test.example.com.` |

> **Примечание:** В обратных зонах октеты IP-адреса указываются в обратном порядке (хост.сеть).

### 3. Настройка на Slave-сервере

```conf
zone "16.172.in-addr.arpa" {
    type slave;
    file "/var/lib/bind/rev.16.172.in-addr.arpa";
    masters { 172.16.0.5; };  // IP-адрес Master-сервера
};
```

### 4. Проверка и верификация

**Проверка синтаксиса:**

```bash
sudo named-checkconf
sudo named-checkzone 16.172.in-addr.arpa /etc/bind/zones/rev.16.172.in-addr.arpa
```

**Тест разрешения PTR:**

```bash
# Проверка обратной зоны через IP
dig -x 172.16.0.5

# Или прямой PTR-запрос
dig @localhost 5.0.16.172.in-addr.arpa PTR
```

**Ожидаемый результат:**

```
;; ANSWER SECTION:
5.0.16.172.in-addr.arpa.  3600  IN  PTR  ns1.test.example.com.
```

### 5. Делегирование обратной зоны

Для публичных IP-адресов обратная зона делегируется провайдером. Пример записи в зоне провайдера:

```dns
16.172.in-addr.arpa.  IN  NS  ns1.your-server.com.
16.172.in-addr.arpa.  IN  NS  ns2.your-server.com.
```

## Дополнительная информация

**Версии:** актуально для BIND 9.18+ (LTS — Long Term Support), 9.20+ (ESV — Extended Support Version).

**Спецификации:** RFC (Request for Comments) 1035 (PTR-записи), RFC 2317 (делегирование подсетей меньше /24).

**Применение:** PTR-записи обязательны для корректной работы почтовых серверов, используются в `traceroute` и диагностических утилитах.

**Теория:** общие концепции зон DNS — [Зоны DNS и SOA-запись](../../../../Networking/Protocols/DNS/dns_zones.md).

**См. также:** [Master-сервер](./master_server_local_zone.md), [Slave-сервер](./slave_server_configuration.md), [Диагностика](./troubleshooting.md).
