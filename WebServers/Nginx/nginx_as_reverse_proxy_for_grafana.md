# Настройка Nginx как обратного прокси для Grafana

Чтобы предоставить доступ к веб-интерфейсу Grafana по стандартному 80-му порту вместо порта 3000, стандартной практикой является использование Nginx в качестве обратного прокси (reverse proxy).

## Конфигурация Nginx

Ниже приведен пример базовой конфигурации для сайта Nginx (например, `/etc/nginx/sites-available/default`).

```nginx
server {
    listen 80;
    server_name your_domain.com; # Замените на ваш домен или IP-адрес

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Важный нюанс: Директива `try_files`

В стандартной конфигурации Nginx для `location /` часто присутствует директива `try_files`.

```nginx
location / {
    # Эта строка конфликтует с Grafana и должна быть удалена или закомментирована
    # try_files $uri $uri/ =404; 
    
    proxy_pass http://localhost:3000;
}
```

Эта директива заставляет Nginx сначала пытаться найти файл на диске, соответствующий запрошенному URI, и только потом передавать запрос дальше. Это нарушает внутреннюю маршрутизацию Grafana, из-за чего веб-интерфейс не будет загружаться корректно.

**Для правильной работы Grafana за прокси, убедитесь, что директива `try_files` отсутствует в блоке `location`, который проксирует запросы к Grafana.**

После внесения изменений в конфигурацию не забудьте проверить синтаксис и перезагрузить Nginx:

```bash
sudo nginx -t
sudo systemctl restart nginx
```

---
**Связанные темы:**
*   [[../../Grafana/grafana_overview.md]]
*   [[nginx_overview.md]]
