# LDAP миграция между реализациями

## Определения

**Миграция LDAP** — процесс переноса данных, конфигурации и политик доступа между различными LDAP-реализациями (OpenLDAP, 389DS, Active Directory и др.).

**LDIF (LDAP Data Interchange Format)** — основной формат для переноса данных между LDAP-серверами.

**Schema Mapping** — процесс сопоставления схем (objectClass, атрибуты) между различными реализациями LDAP.

**DIT Rebuild** — перестройка дерева данных при несовместимости схем или структуры DIT.

**Re-indexing** — пересоздание индексов после импорта данных на новый сервер.

---

## Базовые концепции

### Сравнение LDAP-реализаций

| Характеристика | OpenLDAP | 389DS | Active Directory |
|:---|:---|:---|:---|
| **Конфигурация** | cn=config (OLC) | cn=config + dsconf | ADUC, Group Policy |
| **Схема** | RFC 2307/2307bis | RFC 2307/2307bis + proprietary | proprietary (LDAP) |
| **Репликация** | Syncrepl (pull) | Multi-Master (push) | Multi-Master (DRS) |
| **ACL** | olcAccess | ACI (aci attribute) | DACL/SACL |
| **Движок БД** | MDB | LMDB | NTDS.dit |
| **Порты** | 389/636 | 3389/3636 | 389/636/3268/3269 |

### Типы миграций

| Тип | Описание | Сложность |
|:---|:---|:---|
| **OpenLDAP → 389DS** | Перенос между open-source решениями | Средняя |
| **389DS → OpenLDAP** | Перенос между open-source решениями | Средняя |
| **OpenLDAP/389DS → AD** | Перенос в корпоративную среду | Высокая |
| **AD → OpenLDAP/389DS** | Миграция из Windows-среды | Высокая |
| **Обновление версии** | OpenLDAP 2.4 → 2.6, 389DS 1.x → 3.x | Низкая-Средняя |

## Практические сценарии

### 1. Миграция OpenLDAP → 389DS

#### Шаг 1: Экспорт данных из OpenLDAP

```bash
# Остановка OpenLDAP
sudo systemctl stop slapd

# Экспорт данных
sudo slapcat -b "dc=example,dc=com" -l /tmp/openldap-data.ldif

# Экспорт конфигурации (опционально)
sudo slapcat -b "cn=config" -l /tmp/openldap-config.ldif
```

#### Шаг 2: Подготовка 389DS

```bash
# Создание инстанса
dscreate from-file /tmp/setup.inf

# Создание суффикса
dsconf -D "cn=Directory Manager" ldap://localhost backend suffix create \
  --suffix "dc=example,dc=com" \
  --be-name userRoot

# Создание индексов
dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr uid --type eq,sub

dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr mail --type eq,sub

dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr objectClass --type eq
```

#### Шаг 3: Импорт данных

```bash
# Конвертация формата (если необходимо)
# OpenLDAP использует memberUid, 389DS — member (DN)
# может потребоваться скрипт конвертации

# Импорт данных
dsconf -D "cn=Directory Manager" ldap://localhost \
  backend import userRoot /tmp/openldap-data.ldif
```

#### Шаг 4: Настройка ACL

```bash
# Пример ACI для 389DS (вместо olcAccess OpenLDAP)
dsconf -D "cn=Directory Manager" ldap://localhost aci add "dc=example,dc=com" \
  --name "Allow self write to password" \
  --type "allow" \
  --permission "write" \
  --userdn "ldap:///self" \
  --targetattr "userPassword" \
  --ssf 128
```

#### Шаг 5: Валидация

```bash
# Сравнение количества записей
echo "OpenLDAP:" && grep -c "^dn:" /tmp/openldap-data.ldif
echo "389DS:" && dsidm -b "dc=example,dc=com" userRoot count

# Проверка поиска
ldapsearch -x -H ldap://localhost -D "cn=Directory Manager" -W \
  -b "dc=example,dc=com" "(objectClass=*)" dn | wc -l
```

### 2. Миграция 389DS → OpenLDAP

```bash
# Экспорт из 389DS
dsconf -D "cn=Directory Manager" ldap://389ds-server \
  backend export userRoot --ldif /tmp/389ds-data.ldif

# Конвертация ACI → ACL (ручная или скриптом)

# Импорт в OpenLDAP
sudo systemctl stop slapd
sudo slapadd -b "dc=example,dc=com" -l /tmp/389ds-data.ldif
sudo chown -R ldap:ldap /var/lib/ldap
sudo systemctl start slapd
```

### 3. Миграция OpenLDAP 2.4 → 2.6

```bash
# 1. Экспорт данных (на 2.4)
slapcat -b "dc=example,dc=com" -l /tmp/ldap-2.4.ldif

# 2. Установка OpenLDAP 2.6
sudo dnf install openldap-servers-2.6* openldap-clients-2.6*

# 3. Очистка старой конфигурации
sudo rm -rf /etc/openldap/slapd.d/*
sudo rm -rf /var/lib/ldap/*

# 4. Импорт данных в 2.6
sudo slapadd -b "dc=example,dc=com" -l /tmp/ldap-2.4.ldif

# 5. Настройка конфигурации (только MDB)
# 6. Запуск и проверка
sudo systemctl start slapd
```

### 4. Миграция AD → OpenLDAP/389DS

```bash
# 1. Экспорт из AD (LDAP Browser или ldifde)
ldifde -f /tmp/ad-export.ldif -s dc.example.com \
  -d "dc=example,dc=com" -r "(objectClass=*)" \
  -p subtree

# 2. Конвертация формата AD → POSIX
# - sAMAccountName → uid
# - objectGUID → entryUUID
# - memberOf → member (reverse)
# Требуется скрипт конвертации (Python/ldap3)

# 3. Импорт в целевой сервер
ldapadd -x -D "cn=admin,dc=example,dc=com" -W -f /tmp/ad-converted.ldif
```

### 5. Скрипт конвертации OpenLDAP → 389DS (Python)

```python
#!/usr/bin/env python3
"""Конвертация OpenLDAP LDIF для импорта в 389DS"""

from ldif import LDIFParser
import sys

class Converter(LDIFParser):
    def __init__(self, input_file):
        super().__init__(input_file)

    def handle(self, dn, attrs):
        # Конвертация memberUid → member (если нужно)
        if 'memberUid' in attrs and 'member' not in attrs:
            members = []
            for uid in attrs['memberUid']:
                members.append(f"uid={uid.decode()},ou=people,dc=example,dc=com")
            attrs['member'] = members
            del attrs['memberUid']

        # Вывод в LDIF
        print(f"dn: {dn.decode()}")
        for attr, values in attrs.items():
            for value in values:
                print(f"{attr}: {value.decode()}")
        print()

if __name__ == '__main__':
    converter = Converter(sys.stdin)
    converter.parse()
```

### 6. Тестирование миграции

```bash
# 1. Разворотывание тестового окружения
# 2. Импорт данных
# 3. Проверка целостности:
#    - Количество записей
#    - Количество групп
#    - Вложенность групп
#    - ACL/ACI
#    - Индексы
# 4. Тестирование приложений:
#    - SSSD bind
#    - LDAP-аутентификация в приложениях
#    - Репликация
```

## Дополнительная информация

### Типичные проблемы при миграции

| Проблема | Причина | Решение |
|:---|:---|:---|
| Несовместимость схем | Разные objectClass/атрибуты | Скрипт конвертации, расширение схемы |
| Формат DN | Различия в RDN (uid vs cn) | Маппинг атрибутов |
| ACL/ACI | Разный синтаксис | Ручная конвертация |
| Кодировка | Различия в UTF-8 | Проверка `file -i` LDIF-файла |
| Операционные атрибуты | entryUUID, entryCSN | Исключение из импорта |
| Размер БД | Разный формат хранения | Настройка `olcDbMaxSize` |

### Чеклист миграции

```text
[ ] Бэкап текущего окружения
[ ] Тестовая среда развернута
[ ] Скрипт конвертации написан и протестирован
[ ] Данные экспортированы из источника
[ ] Данные конвертированы в формат назначения
[ ] Данные импортированы в тестовую среду
[ ] Целостность данных проверена
[ ] Приложения протестированы
[ ] ACL/ACI настроены
[ ] Репликация настроена (если применимо)
[ ] План отката подготовлен
[ ] Миграция выполнена в production
[ ] Мониторинг после миграции настроен
```

### См. также

- **[OpenLDAP: установка](./openldap_basics.md)** — утилиты slapcat/slapadd
- **[389DS: Обзор](./389ds/overview.md)** — утилиты dsconf/dsctl
- **[LDAP: основы протокола](./ldap_fundamentals.md)** — схемы и структура DIT
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/index.md)** — настройка клиентов
