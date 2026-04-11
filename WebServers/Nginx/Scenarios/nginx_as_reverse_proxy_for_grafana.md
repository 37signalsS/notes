# Сценарий: Настройка [Nginx](../Core/nginx_overview.md) как обратного прокси для [Grafana](../../../Grafana/grafana_overview.md)

## Определения

**Nginx как обратный прокси для Grafana:** Предоставление доступа к веб-интерфейсу Grafana по стандартному HTTP/HTTPS порту (80/443), используя Nginx в качестве обратного прокси, вместо прямого обращения к порту Grafana (по умолчанию 3000).

---

## Базовые концепции

**[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md):** Сервер, который принимает запросы от клиентов, перенаправляет их на один или несколько бэкенд-серверов и возвращает ответ клиенту. Для клиента это выглядит так, будто он общается напрямую с Nginx.

---

## Практический сценарий: Конфигурация Nginx

Ниже приведен пример базовой конфигурации для сайта Nginx (например, `/etc/nginx/sites-available/grafana.conf`).

```nginx
server {
    listen 80;
    server_name your_domain.com; # Замените на ваш домен или IP-адрес

    location / {
        proxy_pass http://localhost:3000; # Порт Grafana
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

После внесения изменений в конфигурацию не забудьте проверить синтаксис и перезагрузить Nginx:

```bash
sudo nginx -t
sudo systemctl restart nginx
```

---

## Дополнительная информация: Особенности директивы `try_files`

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

---

## Смотрите также

- [Обзор Nginx](../Core/nginx_overview.md)
- [Обзор Grafana](../../../Grafana/grafana_overview.md)
- [Концепция Proxy](../../../Networking/Concepts/proxy.md)
