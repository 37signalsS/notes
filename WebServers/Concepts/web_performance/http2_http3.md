# HTTP/2 и HTTP/3

**SSoT (Single Source of Truth):**
- **[Конфигурация HTTP/2 и HTTP/3 в Nginx](../../Nginx/Performance/nginx_http_versions.md)** — полная документация по настройке
- **[Эволюция HTTP](../../../Networking/Protocols/HTTP/http_versions.md)** — сравнение версий протокола

## Краткая сводка

### HTTP/2

* **Мультиплексирование:** Устраняет проблему "блокировки начала очереди" (head-of-line blocking) на уровне приложения, позволяя отправлять несколько запросов по одному TCP-соединению.
* **Сжатие заголовков (HPACK):** Автоматическое сжатие заголовков.
* **Одно соединение:** Вместо 6 TCP-соединений в HTTP/1.1 используется одно.
* **Приоритизация:** Через механизм `weight` (ограничена TCP-буфером ядра).

### HTTP/3

* **Основан на QUIC (UDP):** Решает проблему Head-of-Line Blocking на транспортном уровне.
* **Встроенный TLS:** Ускоряет установление соединения (0-RTT или 1-RTT).
* **Полная приоритизация:** На уровне приложения (нет ограничений TCP-буфера).
* **Обнаружение клиентами:**
  - Заголовок `Alt-Svc: h3=":443"; ma=86400` (проблема «холодного старта»)
  - DNS-запись типа `HTTPS` (предпочтительный вариант)

## Пример конфигурации Nginx/Angie для HTTP/3

```nginx
# Глобальный контекст (main)
quic_bpf on;              # Требуется ядро Linux с eBPF
quic_gso on;              # Generic Segmentation Offload

server {
    listen 443 quic reuseport;    # UDP для QUIC
    listen 443 ssl http2;         # TCP для HTTP/2 и HTTP/1.1
    
    http3 on;
    add_header Alt-Svc 'h3=":443"; ma=86400';
    
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
}
```

## Рекомендации

1. **DNS-запись HTTPS:** Настройте для ускорения первой загрузки:
   ```dns
   example.com HTTPS 1 . alpn="h2,h3"
   ```

2. **Производительность:** HTTP/2 и HTTP/3 требуют на 20-30% больше ресурсов сервера (CPU/RAM).

3. **Антипаттерны:**
   - Доменный шардинг — избыточен с HTTP/2
   - Конкатенация CSS/JS — менее критична, иногда вредна

4. **Безопасность:** `ssl_early_data` (0-RTT) требует OpenSSL 3.0.1+ и осторожности из-за replay-атак.

---

**Связанные темы:**

* [Оптимизация TLS](./tls_optimization.md) — ускорение безопасного соединения
* [Компрессия контента](./server_compression.md) — Gzip, Brotli, ZSTD
* [Кэширование](./caching.md) — клиентское и серверное кэширование
* [DNS-записи HTTPS/SVCB](../../../Networking/Protocols/DNS/dns_records.md) — обнаружение HTTP/3
