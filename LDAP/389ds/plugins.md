# Плагины 389DS

389DS поддерживает множество плагинов для расширения функциональности. Основные плагины:

## RetroChangeLog

Плагин сохраняет все изменения в отдельной ветке `cn=changelog`. Полезен для:
* Отладки репликации
* Аудита изменений
* Восстановления данных

## MemberOf

Автоматически добавляет атрибут `memberOf` к пользовательским записям, показывая группы, в которых состоит пользователь. Решает проблему "обратного" поиска — вместо поиска групп по пользователю, информация о группах хранится в самой записи пользователя.

## Включение плагинов

Плагины конфигурируются в ветке `cn=config,cn=plugins`. Изменения требуют перезапуска контейнера.

### Пример LDIF для включения плагинов

```ldif
dn: cn=Retro Changelog,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on

dn: cn=MemberOf Plugin,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on
```

### Настройка MemberOf для uniqueMember

```ldif
dn: cn=MemberOf Plugin,cn=plugins,cn=config
changetype: modify
replace: memberOfGroupAttr
memberOfGroupAttr: uniqueMember
```

### Применение изменений

```bash
# На каждом сервере (конфигурация не реплицируется)
docker exec 389ds ldapmodify -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W -f plugin-config.ldif

# Перезапуск контейнера
docker restart 389ds
```

### Проверка конфигурации плагинов

```bash
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "cn=MemberOf Plugin,cn=plugins,cn=config"
```
