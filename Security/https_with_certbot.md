# Настройка HTTPS с помощью Let's Encrypt и Certbot

Certbot — это инструмент для автоматического получения и обновления бесплатных SSL/TLS сертификатов от Let's Encrypt.

## Установка Certbot

*   **Debian/Ubuntu (для Nginx):**
    ```bash
    apt install -y certbot python3-certbot-nginx
    ```
*   **CentOS/RHEL (для Nginx):**
    ```bash
    # В современных дистрибутивах (CentOS 8+, RHEL 8+) используется dnf
    dnf install -y epel-release
    dnf install -y certbot-nginx
    ```

## Настройка Nginx

Certbot должен найти правильный `server_name` в конфигурации Nginx, чтобы автоматически настроить SSL. Убедитесь, что в файле конфигурации вашего сайта (например, `/etc/nginx/sites-available/example.com.conf`) директива `server_name` указана корректно:

```nginx
server_name example.com www.example.com;
```

После проверки синтаксиса (`nginx -t`) перезагрузите Nginx:

```bash
systemctl reload nginx
```

## Получение SSL-сертификата

Запустите Certbot с плагином для Nginx:

```bash
certbot --nginx -d example.com -d www.example.com
```

*   При первом запуске потребуется указать email и согласиться с условиями.
*   Certbot проверит, что вы контролируете домен.
*   Вам будет предложено выбрать, делать ли автоматический редирект с HTTP на HTTPS. Рекомендуется выбрать `Redirect` (вариант 2).

После успешного выполнения Certbot сохранит сертификаты (обычно в `/etc/letsencrypt/live/example.com/`) и автоматически обновит конфигурацию Nginx.

## Настройка автоматического обновления

Сертификаты Let's Encrypt действительны 90 дней. Certbot настраивает автоматическое продление.

*   **Debian/Ubuntu:** Пакет `certbot` создает таймер `systemd` (`certbot.timer`), который запускается дважды в день и обновляет сертификаты, если до истечения срока их действия осталось менее 30 дней.
    Проверить статус таймера:
    ```bash
    systemctl status certbot.timer
    ```

*   **CentOS:** Необходимо добавить задачу в `cron`.
    Откройте `crontab` для редактирования:
    ```bash
    crontab -e
    ```
    Добавьте строку для ежедневной проверки в 4:10 утра:
    ```
    10 4 * * * /usr/bin/certbot renew --quiet
    ```

Для проверки процесса обновления можно запустить "сухой прогон":

```bash
certbot renew --dry-run
```
