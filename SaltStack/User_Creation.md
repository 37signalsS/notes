# Создание пользователя в SaltStack

Напишите состояние SaltStack (Salt State), которое создает пользователя с заданными параметрами. Состояние должно использовать модуль `user.present` для создания пользователя с указанным именем, домашней директорией и оболочкой.

## Входные данные

Три строки:
- Имя пользователя
- Путь к домашней директории
- Путь к оболочке (shell)

## Выходные данные

YAML-конфигурация состояния SaltStack для создания пользователя.

**Sample Input:**

```
webuser
/home/webuser
/bin/bash
```

**Sample Output:**

```yaml
create_webuser:
  user.present:
    - name: webuser
    - home: /home/webuser
    - shell: /bin/bash
```
