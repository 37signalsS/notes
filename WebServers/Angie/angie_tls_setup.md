# Настройка TLS в Angie

**Основным руководством по настройке TLS для Angie следует считать заметку [Оптимальная настройка TLS/SSL в Nginx](../Nginx/Security/nginx_tls_ssl_configuration.md).**

## Ключевые отличия и особенности в Angie

### Поддержка HTTP/3 (QUIC)

Конфигурация для включения HTTP/3 в Angie является более прямолинейной.

```nginx
server {
    # Включаем HTTP/2 для TCP и QUIC (HTTP/3) для UDP
    listen 443 ssl http2;
    listen 443 quic reuseport;

    # ... сертификаты ...
    ssl_certificate /path/to/your_cert.pem;
    ssl_certificate_key /path/to/your_key.pem;

    # Явное включение HTTP/3
    http3 on;

    # Заголовок для обнаружения поддержки HTTP/3 клиентами
    add_header Alt-Svc 'h3=":443"; ma=86400';
}
```

- `listen 443 quic reuseport`: Указывает Angie слушать UDP-порт 443 для протокола QUIC.
- `http3 on`: Включает поддержку HTTP/3.

### DNS-запись типа HTTPS

Для информирования клиентов о поддержке HTTP/3 можно использовать DNS-запись типа `HTTPS`:

```dns
your_domain.com. IN HTTPS 1 . alpn="h2,h3"
```
Это позволяет браузеру сразу установить соединение по самому современному протоколу.

**Для всех остальных аспектов настройки TLS, таких как Keep-Alive, кэширование сессий, использование EC и RSA сертификатов, а также проверки конфигурации, следует обращаться к [руководству по настройке Nginx](../Nginx/Security/nginx_tls_ssl_configuration.md).**
