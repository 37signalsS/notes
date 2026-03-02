# Общие вопросы файрволов Linux

> [Назад к оглавлению](../linux_firewall_management.md)

## Определения

Общие вопросы настройки и управления файрволами в Linux.

## Сохранение правил `iptables`

Правила `iptables` не сохраняются после перезагрузки по умолчанию.

* **Debian/Ubuntu:**

    ```bash
    sudo apt-get update
    sudo apt-get install -y iptables-persistent
    # Для сохранения измененных правил:
    sudo netfilter-persistent save
    ```

* **RHEL/CentOS:**

    ```bash
    sudo yum install -y iptables-services
    sudo systemctl enable --now iptables
    # Для сохранения правил:
    sudo service iptables save
    ```

## Взаимодействие `iptables` и Docker

Docker активно управляет `iptables` для обеспечения сетевой изоляции и проброса портов, добавляя собственные правила в цепочки `DOCKER` и `FORWARD`. Это создает несколько распространенных проблем:

1. **Конфликт с политикой `FORWARD DROP`**: Если вы вручную устанавливаете политику по умолчанию для цепочки `FORWARD` в `DROP`, Docker не сможет доставить трафик в контейнеры.
    * **Решение:** Вместо изменения глобальной политики, добавляйте свои правила в специальную цепочку `DOCKER-USER`. Docker обрабатывает правила из этой цепочки *перед* своими автоматическими правилами, что позволяет безопасно переопределять доступ к контейнерам.

2. **Конфликт `iptables-legacy` и `iptables-nft`**: В современных дистрибутивах `iptables` является слоем совместимости над `nftables`. Если Docker пытается использовать `legacy`-синтаксис, а другая служба (например, `firewalld`) управляет `nftables` напрямую, правила Docker могут "затираться" или не работать.
    * **Решение:** Явно переключить Docker и систему на использование `iptables-legacy`.

Подробный разбор этих проблем и примеры их решения находятся в отдельной заметке: **[Решение проблем: Docker и `iptables`](../../../Docker/Docker_network/troubleshooting/iptables_integration.md)**.

Ниже приведен пример добавления правил в `DOCKER-USER`:

```bash
# Пример: разрешить доступ к порту 8080 контейнера только с IP 1.2.3.4
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -s 1.2.3.4 -j ACCEPT
sudo iptables -I DOCKER-USER -i eth0 -p tcp --dport 8080 -j DROP
```

## `DROP` vs `REJECT`

* `DROP`: Пакеты молча отбрасываются. Предпочтительный способ для внешней сети, так как не раскрывает информацию о хосте и замедляет сканирование портов.
* `REJECT`: Отправителю отправляется ICMP-сообщение (`connection refused`). Может быть полезно для отладки во внутренних, доверенных сетях.

## Полезные команды `iptables`

```bash
# Просмотр правил с номерами строк и счетчиками
sudo iptables -nvL --line-numbers

# Вставить правило на первую позицию в цепочку INPUT
sudo iptables -I INPUT 1 -s 1.2.3.4 -j DROP

# Удаление правила по номеру строки
sudo iptables -D INPUT 1

# Сброс всех правил и счетчиков (ОПАСНО!)
sudo iptables -F
sudo iptables -X
```
