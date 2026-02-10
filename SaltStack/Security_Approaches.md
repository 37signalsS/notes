# Подходы к безопасности SaltStack

## Модель доверия и поверхность атак

SaltStack опирается на модель «master–minion» с брокером сообщений и удалённым исполнением. Основные границы доверия:

*   Master публикует задания и хранит чувствительные данные (pillar, ключи).
*   Minion исполняет модули и возвращает результаты.
*   Дополнительно: API-узлы (salt-api), returners/бэкенды, файловый сервер (gitfs/local), Syndic.

Ключевые угрозы: компрометация ключей, эскалация прав через слишком широкие ACL, утечка секретов через логи/кэш, перехват трафика на 4505/4506, злоупотребление «peer» и опасными модулями (cmd.run).

## Аутентификация и ключи (PKI)

*   Принятие ключей: auto_accept должно быть выключено; предпочтителен ручной процесс или контролируемый autosign по заданным признакам.
*   Подпись публичного ключа мастера: включает проверку подлинности мастера у minion и снижает риск MITM.
*   Жёсткие права на pki-директории и ротация ключей.

Пример master:

```yaml
file_roots:
  base:
    - /srv/salt
pillar_roots:
  base:
    - /srv/pillar

user: root
hash_type: sha256
open_mode: False
auto_accept: False
master_sign_pubkey: True
master_sign_key_name: master_sign
keep_jobs: 24
state_output_diff: False

client_acl:
  ops:
    - 'G@role:app and E@prod-.*':
      - test.ping
      - state.apply
external_auth:
  pam:
    ops:
      - .*
      - '@runner'
      - '@wheel'
rest_cherrypy:
  host: 127.0.0.1
  port: 8000
  ssl_crt: /etc/pki/tls/certs/api.crt
  ssl_key: /etc/pki/tls/private/api.key
```

На minion следует включить проверку подписи мастера:

```vbnet
verify_master_pubkey_sign: True
```

Автопринятие по зернам (строго по шаблону, без глобального auto_accept):

```bash
autosign_grains_dir: /etc/salt/autosign_grains
```

## Разграничение прав и публикация

*   Использовать external_auth + токены для salt-api и ограничивать функции/таргеты через client_acl.
*   Не включать «peer», если он не нужен; при необходимости — белые списки конкретных функций с точным таргетингом.
*   Runner/Wheel операции доступны только доверенным пользователям, так как управляют мастер-состояниями и ключами.

## Работа с секретами

*   Секреты — в pillar (пер-миньонная видимость), а не в state; ограничение экспозиции через таргетинг pillar и изоляцию окружений.
*   Шифрование контента рендерером GPG или интеграция sdb (Vault/KMS).
*   Отключение детальных диффов и бережная настройка логирования.

Пример GPG в pillar:

```ruby
# /srv/pillar/secret.sls
db_password: |
  -----BEGIN PGP MESSAGE-----
  ...
  -----END PGP MESSAGE-----
```

В master рендерер GPG:

```makefile
renderer: jinja | yaml | gpg
gpg_keydir: /etc/salt/gpgkeys
```

## Транспорт и сеть

*   Ограничение доступа к портам 4505/4506 списками контроля на межсетевом экране; привязка API к localhost или внутренней сети.
*   Для gitfs — проверка TLS и подписей; только read-only доступ у мастера к репозиторию состояний.

## Уменьшение мощности модулей

*   Отключение опасных модулей на minion, если не требуются:

```makefile
disable_modules:
  - cmd
  - chef
```

*   Белые списки в «module.run» и аккуратная выдача sudo в окружении minion.

## Аудит и хранение данных

*   Ограниченный срок жизни job cache (keep_jobs), жёсткие права на кеш и ключи, контроль returners (TLS, аутентификация).
*   Раздельные роли пользователей для чтения/выполнения/администрирования; неизменяемые артефакты состояний через CI.
