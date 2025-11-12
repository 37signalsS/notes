# Установка WordPress

Создайте директорию для сайта:

```bash
mkdir /var/www/example.com
```

Назначьте правильного владельца (пользователя веб-сервера):

*   **Ubuntu/Debian (Nginx/Apache):**
    ```bash
    chown -R www-data:www-data /var/www/example.com
    ```
*   **CentOS (Nginx):**
    ```bash
    chown -R nginx:nginx /var/www/example.com
    ```
*   **CentOS (Apache):**
    ```bash
    chown -R apache:apache /var/www/example.com
    ```

## Создание базы данных

Для работы WordPress необходима база данных. Создайте базу данных и пользователя для неё, следуя инструкциям в документе [database_setup.md](./database_setup.md#Создание-базы-данных-и-пользователя).

## Загрузка и настройка WordPress

Перейдите в директорию сайта и скачайте последнюю версию WordPress:

```bash
cd /var/www/example.com
wget https://wordpress.org/wordpress-6.8.3.zip
unzip wordpress-6.8.3.zip
```

Переместите файлы из подпапки `wordpress` в корень сайта и удалите пустую папку и архив:

```bash
mv wordpress/* .
rmdir wordpress
```

Создайте файл конфигурации `wp-config.php` из примера:

```bash
mv wp-config-sample.php wp-config.php
```

Отредактируйте `wp-config.php` и впишите данные для подключения к базе данных, созданной на Шаге 2.

```php
// ...
define( 'DB_NAME', 'exampledb' );
define( 'DB_USER', 'exampledb-user' );
define( 'DB_PASSWORD', '${VAULT_KEY}' );
// ...
```

После этого откройте ваш домен в браузере, чтобы завершить установку через веб-интерфейс.
