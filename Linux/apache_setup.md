# Установка и настройка Apache

    ```bash
    apt update && apt -y install apache2
    ```

    ```bash
    systemctl status apache2
    ```
На Ubuntu и Debian службы после установки запускаются и добавляются в автозапуск автоматически, на Centos это нужно сделать вручную.

## Настройка Firewall (CentOS)

На CentOS после установки нужно отредактировать настройки встроенного фаервола:

```bash
firewall-cmd --permanent --zone=public --add-service=http --add-service=https
firewall-cmd --reload
```

Проверить, что настройки успешно применились, можно с помощью команды:

```bash
firewall-cmd --list-all
```

В блоке `Services` в списке должны отображаться `http` и `https.

## Проверка работы

*   **CentOS/RHEL-подобные:** Теперь можно открыть IP-адрес вашего сервера в браузере — откроется стартовая страница веб-сервера (на современных RHEL-подобных дистрибутивах Apache по умолчанию не имеет приветственной страницы. CentOS 7 и 8 достигли EOL, рекомендуется использовать AlmaLinux/Rocky Linux).
*   **Debian и Ubuntu:** Можно сразу ввести IP-адрес вашего сервера в адресную строку браузера — откроется приветственная страница веб-сервера, размещенная в директории `/var/www/html`.

## Конфигурационные файлы

Расширенные настройки веб-сервера доступны в конфигурационном файле:

*   **Ubuntu и Debian:** `/etc/apache2/apache2.conf`
*   **CentOS:** `/etc/httpd/conf/httpd.conf`

---

## Смотри также

*   [Безопасность веб-серверов Nginx и Apache](../Networking/web_server_hardening.md)
