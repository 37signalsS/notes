# Установка PostgreSQL на Ubuntu 22.04

## Предварительные требования
*   Сервер под управлением Ubuntu 22.04.
*   Пользователь с правами `sudo`.

## Шаг 1: Настройка брандмауэра (UFW)
Перед установкой СУБД рекомендуется настроить брандмауэр для защиты сервера.

1.  Обновите пакеты:
    ```bash
    sudo apt update
    ```
2.  Установите и настройте UFW (Uncomplicated Firewall):
    ```bash
    sudo apt install ufw
    sudo ufw allow OpenSSH
    sudo ufw enable
    ```
3.  Проверьте статус:
    ```bash
    sudo ufw status
    ```

## Шаг 2: Установка PostgreSQL
PostgreSQL доступен в стандартных репозиториях Ubuntu.

1.  Обновите индекс пакетов:
    ```bash
    sudo apt update
    ```
2.  Установите PostgreSQL и дополнительные утилиты:
    ```bash
    sudo apt install postgresql postgresql-contrib
    ```
3.  Запустите сервис и проверьте его статус:
    ```bash
    sudo systemctl start postgresql.service
    sudo systemctl status postgresql.service
    ```

## Шаг 3: Удаление PostgreSQL (при необходимости)
Если требуется полностью удалить СУБД и очистить систему:

1.  Остановите сервис:
    ```bash
    sudo systemctl stop postgresql
    ```
2.  Удалите пакеты и конфигурацию:
    ```bash
    sudo apt-get --purge remove postgresql\*
    ```
3.  Очистите остаточные директории и пользователей:
    ```bash
    sudo rm -r /etc/postgresql/
    sudo rm -r /var/lib/postgresql/
    sudo userdel -r postgres
    sudo groupdel postgres
    ```

### См. также
*   [Управление ролями и БД](./role_management.md)
*   [Настройка брандмауэра UFW](../../../Linux/Networking/Settings/tools/ufw.md)
