# Безопасность и управление секретами в SaltStack

## Определения

- **Модель доверия (Trust Model)**: Иерархическая модель, где Master является доверенным источником конфигураций, а Minion'ы проходят аутентификацию через PKI перед выполнением команд.
- **PKI (Public Key Infrastructure)**: Система на базе RSA-ключей для аутентификации миньонов и AES-шифрования трафика между Master и Minion.
- **Сеансовый ключ (Session Key)**: Симметричный AES-ключ, который мастер периодически ротирует (по умолчанию раз в 24 часа, а также при перезапуске и удалении/отклонении ключа миньона) и использует для шифрования публикаций в шине; сам ключ передается миньону, зашифрованным его публичным ключом. Для передачи Pillar каждому миньону выдается отдельный сеансовый ключ.
- **eAuth (External Authentication)**: Система делегирования аутентификации внешним провайдерам (LDAP, Active Directory, PAM, OAuth2/JWT) для доступа к Salt-API или CLI с выдачей короткоживущих токенов.
- **Publisher ACL**: Механизм разграничения прав доступа локальных пользователей ОС к командам Salt без прав root.
- **Peer Publish**: Возможность миньона выполнять команды на других миньонах или запускать runner'ы на мастере; настраивается опциями `peer` и `peer_run` (по умолчанию отключено).
- **SDB (Salt Data Backend)**: Универсальный интерфейс для динамического получения данных из защищенных хранилищ (Vault, AWS Secrets Manager, keyring) в реальном времени через URI `sdb://<profile>/<path>/<key>`.
- **Шифрование Pillar (Pillar Encryption)**: Механизм хранения секретов в зашифрованном виде в Pillar/SLS-файлах (рендереры GPG или NACL) с расшифровкой на мастере в момент компиляции Pillar.
- **Salt Syndic**: Узел-посредник между Master и локальными мастерами; требует отдельных ключей PKI и конфигурации `syndic_master`. Компрометация Syndic дает доступ к конфигурациям всех подключенных миньонов.
- **Reactor**: Система событийной автоматизации на мастере, реагирующая на события шины (`salt/event/*`). Небезопасная конфигурация reactor может привести к выполнению произвольных состояний на миньонах.
- **GitFS**: Бэкенд файлового сервера Salt, хранящий SLS-файлы в Git-репозитории. Безопасность зависит от прав доступа к репозиторию и версионирования.
- **mTLS (Mutual TLS)**: Двусторонняя TLS-аутентификация, при которой и клиент, и сервер представляют друг другу сертификаты. В Salt применяется между Master и Minion на уровне шины сообщений.
- **FIPS Mode**: Режим работы Salt на системах с включенным FIPS, при котором используются только approved алгоритмы шифрования.

---

## Основные концепции

### 1. Жизненный цикл ключей и PKI

Безопасность начинается с контроля доступа к мастеру и корректной настройки PKI.

**Компоненты PKI и каналы:**
- Каждая сторона генерирует RSA-ключевую пару: `master.pem`/`master.pub` на мастере, `minion.pem`/`minion.pub` на каждом миньоне (каталог `/etc/salt/pki/<master|minion>/`).
- Публикация заданий идет по порту **4505** (Publisher), возврат результатов — по порту **4506** (Retriever). Миньоны сами инициируют исходящие соединения, поэтому на мастере достаточно открыть только эти два входящих порта.
- Фактическое шифрование сообщений выполняется сеансовым AES-ключом, который мастер ротирует по умолчанию раз в 24 часа (а также при перезапуске и удалении/отклонении ключа миньона). Управляется опцией `rotate_aes_key: True` (по умолчанию). Для передачи Pillar каждому миньону выдается отдельный сеансовый ключ.
- `salt-key --rotate-aes-key=False` отключает сброс сеансового ключа при удалении/отклонении ключей — снижает защищенность операции и используется редко (например, в средах с десятками тысяч узлов, где массовая ротация вызывает «шторм» повторной аутентификации всех миньонов).

**Аутентификация миньонов:**
- Доступ к шине имеют только принятые ключи (`salt-key -a <minion>`). Глобальный `auto_accept: True` в продакшене запрещен — ключи принимаются вручную после сверки отпечатков.
- Сверка отпечатков (fingerprint): на мастере `salt-key -F` (все ключи) или `salt-key -f <minion>`; отпечаток на миньоне — локально. Совпадение отпечатков защищает от подмены узла при первом подключении.

**Защита от MitM (подмены мастера):**
- Превентивная проверка отпечатка мастера на миньоне через опцию `master_finger` (отпечаток получается командой `salt-key -F master` на мастере).
- Криптографическое подписывание публичного ключа мастера: `master_sign_pubkey: True` на мастере генерирует ключевую пару `master_sign.pem`/`master_sign.pub`; публичный ключ `master_sign.pub` копируется в `/etc/salt/pki/minion/`, а на миньоне включается `verify_master_pubkey_sign: True`. Только при совпадении настроек с обеих сторон аутентификация проходит (иначе миньон откажется подключаться). `master_sign_key_name` — переопределить имя подписывающей пары; `always_verify_signature: True` — всегда проверять подпись, даже для уже известного ключа мастера.
- `sign_pub_messages: True` — подписывать все публикации мастера в шине событий (миньон проверяет подпись перед обработкой). В конфигурации Multi-Master подписывающая пара должна быть общей для всех мастеров.

**Multi-Master и Syndic:**
- В конфигурации Multi-Master (`master_type: redundant`) миньоны получают список мастеров; подписывающая пара `master_sign` должна быть идентичной на всех мастерах.
- Salt Syndic (`syndic_master: <master-host>`) выступает агентом между Master of Masters и локальными миньонами; Syndic имеет собственный набор ключей PKI и требует отдельного контроля доступа. По умолчанию Syndic не имеет прав на прием ключей от миньонов — эти права должны быть явно ограничены.
- В крупных средах (сотни мастеров) рекомендуется использовать отдельный подписывающий ключ для каждого кластера и регулярно ротировать его через `salt-run rotate.master_sign_key`.

**Ротация и отзыв:**
- При компрометации узла ключ немедленно удаляется (`salt-key -d <minion_id>`) или отклоняется (`salt-key -r <minion_id>`). Для сохранения кэшированных файлов миньона при отзыве используется `preserve_minion_cache: True`.
- Каждое удаление/отклонение ключа ротирует сеансовый AES-ключ и вызывает повторную аутентификацию всех миньонов — массовые операции планируются на окно обслуживания. В крупных средах рекомендуется автоматизировать периодическую ротацию и регулярный аудит списка принятых ключей (`salt-key -L`).

### 2. Авторизация и контроль доступа (ACL)

SaltStack предоставляет три уровня разграничения доступа, объединенных единым синтаксисом матчеров (Access Control System):

1. **`publisher_acl`** — для пользователей, имеющих локальный доступ к терминалу мастера. Управляет функциями, целями и runner'ами, доступными пользователю ОС, без прав root. Дополняется `publisher_acl_blacklist` — глобальным запретом функций (например, `cmd`) и пользователей (например, `root`), действующим поверх любых ACL.
2. **`external_auth` (eAuth)** — для доступа через `salt-api` или сторонние системы. Позволяет использовать корпоративные учетные записи (PAM, LDAP, Active Directory, OAuth2/JWT) и выдает короткоживущие токены (TTL по умолчанию 12 часов, `token_expire`; разрешение пользователю переопределять срок — `token_expire_user_override`). Ограничивается по матчерам целей и функций, включая специальные маркеры `@runner`, `@wheel`, `@jobs`.
3. **`peer` / `peer_run`** — позволяет миньонам выполнять команды на других миньонах (`peer`) или запускать runner'ы на мастере (`peer_run`). По умолчанию отключено; ограничивать и ID миньонов, и набор функций регулярными выражениями.

**Формат правил (одинаков для всех трех систем):**
```yaml
<user|minion-regex>:
  - '<target>':
      - <functions|modules>
  - '<target>':
      - '@runner':
          - <runner-functions>
```
- Цели задаются стандартными матчерами таргетинга (globbing `web-*`, Grains `G@os:RedHat` и др.; не поддерживается только составной compound-матчер).
- Функции задаются через glob (`test.*`, `pkg.*`) или маркеры `@runner`, `@wheel`, `@jobs`.
- Принцип наименьших привилегий: выдавать ровно те функции на те цели, которые нужны роли.

### 3. Управление секретами (Secret Management)

Секреты никогда не должны находиться в открытом виде в Git или SLS-файлах. Варианты — от простого к сложному.

**Методы шифрования Pillar (расшифровка на мастере):**
- **GPG-рендерер** — классический асимметричный метод. Значение шифруется публичным ключом мастера и расшифровывается только им при компиляции Pillar. Ключи по умолчанию хранятся в `/etc/salt/gpgkeys` (опция `gpg_keydir`).
- **NACL-рендерер** — современная альтернатива GPG на базе PyNaCl (libsodium). Компактные однострочные значения `NACL[...]`, проще в настройке и быстрее. Поддерживает sealedbox (шифрование публичным ключом: разработчики могут шифровать, но не расшифровывать) и secretbox (симметричный ключ).
- **asymmetric** — низкоуровневые операции подписи/проверки (RSA/ECDSA/Ed25519/Ed448) без зависимости от GPG (модуль доступен с Salt 3008.0).
- Механизм `decrypt_pillar` позволяет указать, какие именно ключи Pillar должны быть расшифрованы (рендерер задается в `decrypt_pillar_default`/`decrypt_pillar_renderers`). Для Pillar в CLI используется аргумент `pillar_enc=gpg`.

Примечание: готовая реализация шифрования Fernet в ядре Salt отсутствует (встроенные рендереры шифрования — только gpg/nacl/asymmetric). Для шифрования секретов в Pillar используйте NACL или GPG.

**Интеграция с внешними хранилищами секретов:**
- **Vault** — полноценная интеграция ([обзор Vault](../Vault/overview.md)): выполнение через модуль `vault.read_secret`, загрузка данных в Pillar через ext_pillar `vault` либо чтение по требованию через SDB. Мастер аутентифицируется в Vault (token или AppRole) и выдает каждому миньону собственный краткосрочный токен с ограниченным набором политик — секреты не хранятся ни в конфигурации, ни в кэше миньона.
- **SDB (Salt Data Backend)** — универсальный интерфейс подстановки значений из защищенных хранилищ в конфигурации, Pillar и состояния через URI `sdb://<profile>/<path>/<key>`. Профиль описывает драйвер (vault, env, keyring, yaml и др.) и параметры подключения.

### 4. Безопасность файлового сервера

Файловый сервер Salt (Salt File Server) раздает миньонам SLS-файлы, статические файлы и шаблоны из `file_roots`. Компрометация файлового сервера ведет к выполнению произвольного кода на всех миньонах.

**Принципы безопасности:**
- **Изоляция окружений**: `file_roots` и `pillar_roots` должны соответствовать веткам Git (`base`, `staging`, `prod`). Никогда не храните production-секреты в `base`.
- **GitFS**: при использовании GitFS (`gitfs_provider: gitpython` или `pygit2`) права на репозиторий должны соответствовать принципу наименьших привилегий. Мастер должен иметь только read-доступ; write-доступ (push) должен быть ограничен CI/CD-пользователем с отдельным ключом.
- **Права на каталоги**: `file_roots` и `pillar_roots` должны принадлежать пользователю `salt: salt` с правами `750` (или stricter). Доступ на запись для группы/others запрещен.
- **Валидация SLS**: включите `file_client: local` при разработке на мастер-хосте для проверки синтаксиса SLS перед пушем: `salt-call --local state.apply test=True`.

### 5. Безопасность Salt-API и сетевого периметра

Salt-API — единственный компонент, принимающий входящие соединения из ненадежных сетей. Его компрометация эквивалентна компрометации мастера при недостаточных ACL.

**Обязательные меры:**
- **TLS**: HTTPS обязателен. Встроенный `rest_cherrypy` настраивается через `ssl_crt`, `ssl_key` (опционально `ssl_chain`, `ssl_ca_certs`). `disable_ssl: True` передает учетные данные в открытом виде и недопустим в продакшене.
- **Обратный прокси**: размещение Salt-API за Angie/Nginx с HSTS, rate limiting и современными шифрами. Тогда SSL-опции `rest_cherrypy` не используются, а терминация TLS выполняется на прокси.
- **Строгие настройки прокси**: HSTS, ограничение методов (GET/POST), CORS (ограничение источников, `rest_cherrypy: cors_origin`), лимиты на размер запросов и частоту (rate limiting).
- **Токены**: передача токена через query-строку (`?token=`) не поддерживается; используется заголовок `X-Auth-Token` или cookie сессии. Авторизацию выполняет система eAuth, а не сам Salt-API.
- **Сессии**: `enable_sessions: True` с `session_store: cache` (или `redis` для кластера). Время жизни сессии должно быть минимальным (`session_timeout: 3600`).
- **Сетевые группы**: Salt-API должен быть доступен только с управляющих хостов (бастионы, CI/CD-раннеры). Файрвол на мастере (nftables/iptables) или security group ограничивает доступ к порту 8000.

### 6. Аудит и комплаенс

- **Журналирование событий**: все события шины (`salt/job/*/new`, `salt/job/*/ret`) логируются через `event_return` в выбранный returner; наблюдение в реальном времени — `salt-run state.event`.
- **Salt Returners**: отправка результатов выполнения команд напрямую в защищенную БД или SIEM (PostgreSQL, Redis, Elasticsearch, Splunk — в т.ч. через hubblestack). Настройка `master_job_cache` и `ext_job_cache`.
- **Compliance**: модули **hubblestack** (`hubblestack_nova` — проверки CIS, `hubblestack_pillar`) или встроенные проверки соответствия стандартам CIS.
- **Ограничение кэша**: `pillar_cache` хранит отрендеренные Pillar в кэше мастера без шифрования — включать только при острой необходимости производительности, убедившись в безопасности каталога кэша.

---

## Практические сценарии

### 1. Настройка eAuth с интеграцией PAM

Позволяет пользователю `devops_admin` выполнять команды через Salt-API, аутентифицируясь по системному паролю, с ограничением на цели и функции.

```yaml
# /etc/salt/master.d/eauth.conf
external_auth:
  pam:
    devops_admin:
      - 'web-*':
        - test.ping
        - state.apply
      - '@runner':
        - jobs.lookup_jid

token_expire: 43200                 # TTL токена eAuth (по умолчанию 12 часов)
token_expire_user_override: False
```

**Валидация:**
```bash
# Получение токена через CLI
salt -a pam -T '*' test.ping
# → token выдан, результат test.ping возвращен

# Проверка срока действия токена
salt-run auth.token_list devops_admin
# → вывод списка активных токенов с TTL
```

### 2. Шифрование секретов GPG в Pillar

1. На мастере создаем keyring и ключ (под пользователем `salt`):
```bash
gpg --homedir /etc/salt/gpgkeys --gen-key
```
2. Указываем keyring в конфигурации мастера:
```yaml
# /etc/salt/master.d/gpg.conf
gpg_keydir: /etc/salt/gpgkeys
gpg_decrypt_must_succeed: True
```
3. Шифруем значение публичным ключом мастера:
```bash
echo -n 'super-secret' | gpg --homedir /etc/salt/gpgkeys --armor --batch --trust-model always --encrypt -r <fingerprint>
```
4. Вставляем блок `-----BEGIN PGP MESSAGE-----` в Pillar и указываем рендерер:
```yaml
# /srv/pillar/secrets.sls
#!yaml|gpg
api_key: |
  -----BEGIN PGP MESSAGE-----
  ... (armor) ...
  -----END PGP MESSAGE-----
```
Расшифровка выполняется только на мастере; миньону передается уже расшифрованное значение по защищенному каналу. Альтернатива — `decrypt_pillar` для выборочной расшифровки отдельных ключей.

**Валидация:**
```bash
# Проверка, что Pillar компилируется без ошибок
salt '*' pillar.items
# → секретный ключ присутствует в выводе в открытом виде (только на миньоне)
salt-call --local pillar.get api_key
# → на мастере расшифрованное значение
```

### 3. Шифрование секретов NACL в Pillar (современная альтернатива GPG)

1. Генерируем пару ключей (секретный ключ остается только на мастере):
```bash
salt-call --local nacl.keygen /root/.nacl
# создает /root/.nacl (секретный) и /root/.nacl.pub (публичный)
```
2. Указываем ключ в конфигурации мастера для расшифровки при компиляции Pillar:
```yaml
# /etc/salt/master.d/nacl.conf
nacl.config:
  keyfile: /root/.nacl
```
3. Шифруем значение (sealedbox — публичным ключом, расшифровать может только мастер):
```bash
salt-call --local nacl.enc "super-secret" pk_file=/root/.nacl.pub
# → NACL[gAAAAAB...]
```
4. Вставляем в Pillar:
```yaml
# /srv/pillar/secrets.sls
#!yaml|nacl
api_key: NACL[gAAAAAB...]
```

**Валидация:**
```bash
# Проверка расшифровки на мастере
salt-call --local pillar.get api_key
# → super-secret
```

### 4. Интеграция с HashiCorp Vault

1. Настройка подключения мастера (token или AppRole):
```yaml
# /etc/salt/master.d/vault.conf
vault:
  server:
    url: https://vault.example.com:8200
  auth:
    method: token
    token: <master-token>
  policies:
    assign:
      - saltstack/minions
      - saltstack/{minion}
```
2. Разрешаем миньонам получать токены через runner-систему:
```yaml
# /etc/salt/master.d/peer_run.conf
peer_run:
  .*:
    - vault.get_config
    - vault.generate_new_token
```
3. Использование:
```bash
salt '*' vault.read_secret secret/salt       # весь секрет
salt '*' vault.read_secret secret/salt mykey # конкретный ключ
```
4. Загрузка секретов прямо в Pillar:
```yaml
# в конфигурации мастера
ext_pillar:
  - vault: path=secret/salt
```
5. Либо SDB-запрос по требованию: профиль `myvault: driver: vault` + использование `sdb://myvault/secret/passwords/mypassword` (для KV v2 корректный путь монтирования добавляется автоматически).

**Валидация:**
```bash
# Проверка подключения к Vault
salt-run vault.generate_new_token
# → временный токен для миньона

# Проверка чтения секрета
salt '*' vault.read_secret secret/salt mykey
# → значение секрета

# Проверка, что секрет не кэшируется в логах
grep -r "mykey" /var/log/salt/master | grep -v "masked"
# → вывод должен быть пустым или содержать только [WARNING] о маскировании
```

### 5. Защита канала Master–Minion от подмены

На мастере:
```yaml
# /etc/salt/master.d/pki.conf
master_sign_pubkey: True
sign_pub_messages: True
```
Скопировать `master_sign.pub` на каждый миньон в `/etc/salt/pki/minion/` и включить проверку:
```yaml
# /etc/salt/minion.d/master.conf
verify_master_pubkey_sign: True
master_finger: ec:81:7c:f1:8d:cf:2a:f6:a3:af:76:cd:5f:be:aa:73
```
Для получения `master_finger` используется `salt-key -F master` на мастере.

**Валидация:**
```bash
# На миньоне: проверка, что миньон отклоняет неподписанного мастера
# 1. Временно отключите verify_master_pubkey_sign на миньоне
# 2. Удалите подпись на мастере: rm /etc/salt/pki/master/master_sign.pem
# 3. Перезапустите master: systemctl restart salt-master
# 4. На миньоне: salt-call test.ping
# → Minion не может подключиться, в логах: "does not match the master's public key signature"
```

### 6. Харденинг (укрепление) системы

- **Минимальные привилегии**: запуск Master и Minion от непривилегированного пользователя `salt` (опция `user` в конфигурации); приватные ключи в `/etc/salt/pki/**` — только для владельца (chmod 600).
- **Сетевая изоляция**: файрволом ограничить доступ к портам 4505/4506 на мастере только подсетями миньонов; Salt-API — только с управляющих хостов.
- **Отключение опасных модулей** на миньонах:
```yaml
# /etc/salt/minion.d/hardening.conf
disable_modules:
  - cmd
  - virt
disable_returners:
  - sqlite3
```
- **Запрет черного списка функций поверх ACL** на мастере:
```yaml
# /etc/salt/master.d/hardening.conf
publisher_acl_blacklist:
  users:
    - root
  modules:
    - cmd
```
- **Журналирование**: `job_cache: True`, `keep_jobs: 24` (срок хранения кэша заданий в часах) и `event_return: <returner>` для отправки событий шины в SIEM.
- Официальный [Hardening Guide](https://docs.saltproject.io/en/latest/topics/hardening.html) содержит полный чек-лист.

**Валидация:**
```bash
# Проверка прав на PKI-каталог
stat -c "%a %U %G" /etc/salt/pki/master/master.pem
# → 600 salt salt

# Проверка запуска от непривилегированного пользователя
ps -eo pid,user,comm | grep salt
# → все процессы salt должны принадлежать пользователю salt, а не root
```

### 7. Настройка eAuth с интеграцией LDAP/Active Directory

Позволяет использовать корпоративные учетные записи для доступа к Salt-API, с разграничением по группам AD.

```yaml
# /etc/salt/master.d/eauth.conf
external_auth:
  ldap:
    # Матчер для группы AD/LDAP
    'CN=Salt-Admins,OU=Groups,DC=example,DC=com':
      - 'web-*':
        - test.ping
        - state.apply
        - pkg.install
      - '@runner':
        - jobs.lookup_jid
        - state.orchestrate

# Конфигурация подключения к LDAP
# /etc/salt/master.d/ldap.conf
user_auth:
  auth.list: ['active_directory']
  auth.active_directory.server: ldap://dc01.example.com
  auth.active_directory.port: 389
  auth.active_directory.basedn: 'DC=example,DC=com'
  auth.active_directory.groupou: 'Groups'
  auth.active_directory.require_group: true
  auth.active_directory.groupfilter: '(&(cn=Salt-Admins)(objectclass=group))'
```

**Валидация:**
```bash
# Проверка аутентификации LDAP-пользователя
salt -a ldap -T 'web-*' test.ping
# → аутентификация через LDAP, результат test.ping

# Проверка, что пользователь не из группы Salt-Admins получает отказ
salt -a ldap -T 'web-*' test.ping
# → AuthenticationError: "not authorized"
```

### 8. Настройка eAuth с интеграцией OAuth2/JWT

Использование OAuth2-провайдера (Keycloak, Okta) для аутентификации в Salt-API.

```yaml
# /etc/salt/master.d/eauth.conf
external_auth:
  oauth2:
    'oauth2-client-app':
      - 'web-*':
        - test.ping
        - state.apply
      - '@runner':
        - jobs.lookup_jid

# Конфигурация OAuth2
# /etc/salt/master.d/oauth2.conf
oauth2:
  provider: keycloak
  client_id: salt-api-client
  client_secret: <client-secret>
  issuer_url: https://keycloak.example.com/realms/salt
  scopes:
    - salt:api:read
    - salt:api:write
  audience: salt-api
  jwks_url: https://keycloak.example.com/realms/salt/protocol/openid-connect/certs
```

**Валидация:**
```bash
# Получение токена у OAuth2-провайдера
curl -s -X POST https://keycloak.example.com/realms/salt/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=salt-api-client" \
  -d "client_secret=<client-secret>" \
  -d "username=devops_admin" \
  -d "password=***" \
  -d "scope=salt:api:read"
# → access_token

# Использование токена
curl -sSk https://salt-master:8000/run \
  -H "Authorization: Bearer <access_token>" \
  -d client=local \
  -d tgt='web-*' \
  -d fun=test.ping
# → [{"return": true}]
```

### 9. Размещение Salt-API за обратным прокси (Angie/Nginx)

Полная конфигурация терминации TLS и ограничения доступа.

```nginx
# /etc/angie/conf.d/salt-api.conf
server {
    listen 443 ssl http2;
    server_name salt-api.example.com;

    ssl_certificate     /etc/pki/tls/certs/salt-api.crt;
    ssl_certificate_key /etc/pki/tls/certs/salt-api.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;

    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=salt_api:10m rate=10r/s;

    location / {
        limit_req zone=salt_api burst=20 nodelay;
        proxy_pass https://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Таймауты
        proxy_connect_timeout 10s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
```

```yaml
# /etc/salt/master.d/rest_cherrypy.conf
rest_cherrypy:
  port: 8000
  bind_address: 127.0.0.1  # слушаем только на localhost
  disable_ssl: True         # SSL terminates on proxy
  enable_sessions: True
  session_store: redis      # для кластера
  session_timeout: 3600
  cors_origin: ''           # запретить CORS по умолчанию
  cors_allow_credentials: false
```

**Валидация:**
```bash
# Проверка, что Salt-API слушает только на localhost
ss -tlnp | grep 8000
# → LISTEN 0 128 127.0.0.1:8000

# Проверка HSTS
curl -sI https://salt-api.example.com | grep -i strict-transport-security
# → Strict-Transport-Security: max-age=31536000; includeSubDomains

# Проверка, что HTTP редиректирует на HTTPS (при наличии)
curl -sI http://salt-api.example.com | grep -i location
# → Location: https://salt-api.example.com
```

### 10. Защита канала Master–Minion от подмены

На мастере:
```yaml
# /etc/salt/master.d/pki.conf
master_sign_pubkey: True
sign_pub_messages: True
```
Скопировать `master_sign.pub` на каждый миньон в `/etc/salt/pki/minion/` и включить проверку:
```yaml
# /etc/salt/minion.d/master.conf
verify_master_pubkey_sign: True
master_finger: ec:81:7c:f1:8d:cf:2a:f6:a3:af:76:cd:5f:be:aa:73
```
Для получения `master_finger` используется `salt-key -F master` на мастере.

**Валидация:**
```bash
# На миньоне: проверка, что миньон отклоняет неподписанного мастера
# 1. Временно отключите verify_master_pubkey_sign на миньоне
# 2. Удалите подпись на мастере: rm /etc/salt/pki/master/master_sign.pem
# 3. Перезапустите master: systemctl restart salt-master
# 4. На миньоне: salt-call test.ping
# → Minion не может подключиться, в логах: "does not match the master's public key signature"
```

### 11. Multi-Master и Syndic безопасность

**Multi-Master (redundant mode):**
- Все мастера должны иметь идентичный `master_sign` ключ для согласованной подписи публикаций.
- `master_type: redundant` в конфигурации миньона указывает список мастеров: `master: [master1, master2, master3]`.
- При деактивации мастера из ротации требуется ручное удаление его ключа из `/etc/salt/pki/minion/` на миньонах.

**Syndic:**
- Syndic не должен иметь прав на прием ключей миньонов (`open_mode: False`, `auto_accept: False` на Syndic).
- Конфигурация Syndic (`/etc/salt/master.d/syndic.conf`):
```yaml
syndic_master: master.example.com
id: syndic-east
```
- Master of Masters должен иметь явный список доверенных Syndic в `peer` конфигурации, иначе Syndic не сможет возвращать результаты.
- Аудит подключений Syndic: проверяйте логи мастера на тег `salt/syndic/*` и убедитесь, что IP Syndic соответствует ожидаемому.

**Валидация:**
```bash
# Проверка, что Syndic не является master для миньонов
salt-key -L
# → Syndic не должен иметь accepted_minion_keys кроме своих собственных

# Проверка подключения Syndic к Master
salt-run manage.up
# → список миньонов, подключенных через Syndic, должен совпадать с фактическим
```

### 12. Безопасность Reactor и Event Bus

Reactor выполняет SLS-состояния на миньонах по событиям шины. Небезопасный reactor — один из самых опасных векторов атаки.

**Принципы безопасности:**
- Reactor должен обрабатывать только явно разрешенные теги событий. Глобальный тег `*` запрещен в продакшене.
- Файлы reactor должны иметь права `640` (`root:salt`), чтобы предотвратить модификацию непривилегированными пользователями.
- Используйте отдельный `file_roots` для reactor (`reactor_roots`) с правами только на чтение для пользователя `salt`.

```yaml
# /etc/salt/master.d/reactor.conf
reactor:
  - 'salt/beacon/*/diskusage':
    - /srv/reactor/disk_alert.sls
  - 'salt/job/*/ret':
    - /srv/reactor/job_audit.sls

reactor_roots:
  - /srv/reactor
```

**Валидация:**
```bash
# Проверка прав на reactor-файлы
ls -la /srv/reactor/
# → -rw-r----- 1 root salt ... disk_alert.sls

# Проверка, что reactor не реагирует на все события
salt-run reactor.list
# → вывод должен содержать только явно разрешенные теги
```

### 13. Безопасность Salt-SSH roster

Salt-SSH не использует постоянные агенты, но roster-файл содержит учетные данные для SSH-доступа.

**Принципы безопасности:**
- Roster-файл (`/etc/salt/roster` или `--roster-file`) должен иметь права `600` (`root:root`), так как содержит IP-адреса, пользователей и пути к ключам SSH.
- SSH-ключи для Salt-SSH должны быть отдельной парой ключей с минимальными правами (только необходимые команды, ограничение по `from` в `authorized_keys`).
- Thin-файлы в `/tmp/` на целевом узле удаляются после выполнения: `salt-ssh --clean`.

```yaml
# /etc/salt/roster
web-01:
  host: 192.168.1.10
  user: salt-ssh
  priv: /etc/salt/ssh_keys/salt_rsa
  sudo: True
  tty: True
```

**Валидация:**
```bash
# Проверка прав на roster-файл
stat -c "%a %U %G" /etc/salt/roster
# → 600 root root

# Проверка, что SSH-ключ имеет минимальные права
ssh -i /etc/salt/ssh_keys/salt_rsa salt-ssh@web-01 'whoami'
# → salt-ssh

# Проверка отсутствия thin-файлов после clean
ls -la /tmp/.*salt* /tmp/bootstrap* 2>/dev/null
# → файлов нет (после salt-ssh --clean)
```

---

## Дополнительная информация

### Безопасность Salt-API

- **TLS**: HTTPS обязателен. Встроенный `rest_cherrypy` настраивается через `ssl_crt`, `ssl_key` (опционально `ssl_chain`, `ssl_ca_certs`). `disable_ssl: True` передает учетные данные в открытом виде и недопустим в продакшене.
```yaml
rest_cherrypy:
  port: 8000
  ssl_crt: /etc/pki/tls/certs/salt-api.crt
  ssl_key: /etc/pki/tls/certs/salt-api.key
  enable_sessions: True
  session_store: cache
```
- Рекомендуется размещать Salt-API за обратным прокси (Angie/Nginx) с HSTS и современными шифрами; тогда SSL-опции `rest_cherrypy` не используются, а терминация TLS выполняется на прокси.
- **Строгие настройки прокси**: HSTS, ограничение методов (GET/POST), CORS (ограничение источников, `rest_cherrypy: cors_origin`), лимиты на размер запросов и частоту (rate limiting).
- **Токены**: передача токена через query-строку (`?token=`) не поддерживается; используется заголовок `X-Auth-Token` или cookie сессии. Авторизацию выполняет система eAuth, а не сам Salt-API.
- Аутентификация для REST — через eAuth (PAM/LDAP/AD) или OAuth2/JWT; управление токенами — runner `auth.mk_token`.

### Аудит и комплаенс

- **Журналирование событий**: все события шины (`salt/job/*/new`, `salt/job/*/ret`) логируются через `event_return` в выбранный returner; наблюдение в реальном времени — `salt-run state.event`.
- **Salt Returners**: отправка результатов выполнения команд напрямую в защищенную БД или SIEM (PostgreSQL, Redis, Elasticsearch, Splunk — в т.ч. через hubblestack). Настройка `master_job_cache` и `ext_job_cache`.
- **Compliance**: модули **hubblestack** (`hubblestack_nova` — проверки CIS, `hubblestack_pillar`) или встроенные проверки соответствия стандартам CIS.
- **Ограничение кэша**: `pillar_cache` хранит отрендеренные Pillar в кэше мастера без шифрования — включать только при острой необходимости производительности, убедившись в безопасности каталога кэша.

### Версии и совместимость

- **Salt 3008 LTS**: актуальная ветка с активной поддержкой; подробный жизненный цикл версий — в [Архитектуре](Architecture.md). Требует Python 3, поддерживает Python 3.12+.
- **Новое в безопасности (3008.0)**: модуль `asymmetric` (подпись/проверка без GPG); значения Pillar оборачиваются в SafeDict/SafeList с маскировкой секретов (Pydantic SecretStr/SecretBytes) для безопасного логирования, авто-редактирование литералов Pillar в логах состояний и заданиях миньонов.
- **FIPS Mode**: с Salt 3006 поддерживается работа на системах в режиме FIPS — ядро использует библиотеку `cryptography`, которая принудительно применяет FIPS-алгоритмы (SHA-224 на основе OAEP/PKCS1v15 вместо SHA-1 по умолчанию). Настройка — опции `fips_mode`, `encryption_algorithm`, `signing_algorithm`, `publish_signing_algorithm`.

### Устранение неполадок (Troubleshooting)

**PKI и аутентификация:**

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Minion did not return. No response received` | Минуем не подключен к мастеру, ключ отклонен или истек сеансовый ключ | Проверить `salt-key -L`, убедиться что ключ accepted; проверить firewall (4505/4506) |
| `Authentication failure` | Несовпадение ключей, MitM-атака | Проверить `master_finger` на миньоне; включить `master_sign_pubkey: True` и `verify_master_pubkey_sign: True` |
| `Salt-API 403 Forbidden` | Недостаточно прав eAuth или истек токен | Проверить правила `external_auth`, получить новый токен через `/login` |
| `Key rotation storm` | Массовое удаление ключей в крупной среде | Использовать `salt-key --rotate-aes-key=False` при массовых операциях; планировать ротацию на окно обслуживания |

**Шифрование Pillar:**

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `gpg: decryption failed` | Отсутствует секретный ключ или неверный fingerprint | Проверить `gpg_keydir`, права на каталог, наличие ключа в `/etc/salt/gpgkeys` |
| `nacl.decrypt error` | Неверный путь к `keyfile` или поврежденный ключ | Проверить `nacl.config.keyfile`, права на `/root/.nacl` (600) |
| `Pillar не подгружается` | Ошибка синтаксиса в SLS или отсутствие секрета в Vault | Выполните `salt '*' saltutil.refresh_pillar` и проверьте логи мастера |

**Vault и SDB:**

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `VaultAuthError` | Неверный token или AppRole, истек срок | Проверить `vault.auth.token` или AppRole credentials; обновить токен мастера |
| `SDB get failed` | Неверный URI или драйвер SDB | Проверить профиль в `sdb` конфигурации мастера: `sdb://myvault/secret/path` |

### Лучшие практики (Best Practices)

1. **Принцип наименьших привилегий**: каждый пользователь/сервис получает ровно те права, которые необходимы для выполнения работы. eAuth правила должны быть максимально узкими.
2. **Беспарольный доступ**: исключите парольную аутентификацию для Salt-API; используйте сертификаты клиентов (mTLS) или OAuth2 вместо basic auth.
3. **Регулярный аудит ключей**: еженедельно выполняйте `salt-key -L` и сверяйте список accepted ключей с CMDB. Автоматизируйте уведомления о новых ключах через Reactor.
4. **Изоляция окружений**: `saltenv` и `pillarenv` должны соответствовать веткам Git; никогда не храните production-секреты в `base`.
5. **Аварийное восстановление**: регулярный бэкап PKI, `file_roots`, `pillar_roots` и Job Cache. Тестируйте восстановление на стенде.
6. **Отсутствие plain-text секретов в Git**: даже зашифрованные секреты (GPG/NACL) должны храниться в отдельном репозитории с доступом только для администраторов. Ротация ключей шифрования — раз в 90 дней.
7. **Журналирование и SIEM**: все события Salt должны поступать в централизованный SIEM. Настройте алерты на `salt/auth` (неудачные аутентификации), `salt/key` (новые/удаленные ключи), `salt/job/*/ret` (выполнение чувствительных модулей).
8. **Проверка целостности файлов**: используйте `file.check_managed` с `hash_type: sha256` для критических конфигураций; периодически проверяйте контрольные суммы `file_roots` и `pillar_roots`.

### Пограничные случаи и ограничения (Edge Cases)

- **Огромные среды (>50 000 миньонов)**: массовая ротация AES-ключа при удалении/отклонении ключей вызывает «шторм» повторной аутентификации. Используйте `salt-key --rotate-aes-key=False` и планируйте ротацию на несколько волн.
- **Внешние атаки на шину**: порты 4505/4506 не должны быть доступны из внешних сетей. Миньоны инициируют соединения, поэтому нет необходимости открывать эти порты для входящих соединений извне.
- **Salt-SSH и эфемерные узлы**: thin-файлы в `/tmp/` могут содержать чувствительные данные. Используйте `salt-ssh --clean` после работы и монтируйте `/tmp` в tmpfs.
- **Pillar Cache**: включает хранение расшифрованных Pillar в кэше мастера (`/var/cache/salt/master/pillar/`). В режиме `pillar_cache: True` права на каталог должны быть строго ограничены (`700 salt:salt`).
- **FIPS-системы**: некоторые модули Salt (например, `nacl`) могут не работать в FIPS-режиме из-за ограничений на алгоритмы. Тестируйте совместимость перед развертыванием.

---

**Полезные ссылки:**
- [Архитектура SaltStack (PKI и порты)](Architecture.md)
- [Управление пользователями и SSH](User_Creation.md)
- [Vault: обзор и управление секретами](../Vault/overview.md)
- [Аудит и комплаенс (обзор)](../Security/audit_and_compliance_overview.md)
- [Управление секретами (обзор)](../Security/Concepts/secrets_management_overview.md)
- [Hardening Guide (официальная документация)](https://docs.saltproject.io/en/latest/topics/hardening.html)
