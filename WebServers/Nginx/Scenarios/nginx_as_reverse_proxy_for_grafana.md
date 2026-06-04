# Настройка Nginx как обратного прокси для Grafana

## 1. Определения

**Nginx в качестве обратного прокси для Grafana** — сценарий развёртывания, при котором Nginx выступает посредником, принимая запросы на стандартных портах (80/443) и перенаправляя их на внутренний порт Grafana (по умолчанию 3000).

* **[Nginx](../Core/nginx_overview.md)** — веб-сервер и обратный прокси.
* **[Grafana](../../../Grafana/grafana_overview.md)** — платформа для визуализации и анализа данных мониторинга.
* **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — сервер, который принимает запросы от клиентов и направляет их на внутренние серверы (бэкенды).

## 2. Базовые концепции

Использование обратного прокси для Grafana позволяет:

1. **Централизовать доступ**: использовать стандартные HTTP (HyperText Transfer Protocol) и HTTPS (HyperText Transfer Protocol Secure) порты.
2. **Обеспечить безопасность**: настроить SSL/TLS-терминацию на уровне Nginx, скрыть внутреннюю структуру сети.
3. **Упростить маршрутизацию**: использовать доменные имена вместо IP-адресов с указанием портов.
4. **Управлять доступом**: добавить дополнительную аутентификацию или ограничение доступа по IP на уровне веб-сервера.

## 3. Практический сценарий

### 3.1. Конфигурация виртуального хоста Nginx

Для настройки создайте файл конфигурации (например, `/etc/nginx/sites-available/grafana.conf`) со следующим содержимым:

```nginx
server {
    listen 80;
    server_name your_domain.com; # Замените на домен или IP-адрес

    location / {
        proxy_pass http://localhost:3000; # Порт Grafana
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3.2. Применение настроек

После создания конфигурации необходимо проверить её синтаксис и перезагрузить сервис Nginx:

```bash
# Проверка синтаксиса
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезагрузка Nginx
sudo systemctl reload nginx
```

## 4. Дополнительная информация

### Особенности директивы `try_files`

При проксировании запросов к Grafana **не рекомендуется** использовать директиву `try_files` в блоке `location /`.

```nginx
location / {
    # Эта строка конфликтует с Grafana и должна быть удалена
    # try_files $uri $uri/ =404; 
    
    proxy_pass http://localhost:3000;
}
```

Директива `try_files` заставляет Nginx сначала искать файлы на локальном диске. Если запрос совпадает с существующим путём, Nginx отдаст статический файл или вернёт ошибку, не передавая запрос бэкенду. Это нарушает внутреннюю маршрутизацию и логику работы Grafana, что приводит к некорректной загрузке интерфейса.

### См. также

* **[Обзор Nginx](../Core/nginx_overview.md)**
* **[Обзор Grafana](../../../Grafana/grafana_overview.md)**
* **[Прокси-серверы: концепции](../../../Networking/Concepts/proxy.md)**
