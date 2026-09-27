# Pillar продвинутый

## Определения

- **Pillar merging**: Механизм объединения данных из разных источников Pillar (pillar_roots, ext_pillar, папки окружений) в единый словарь для каждого миньона.
- **`pillar_source_merging`**: Стратегия слияния Pillar данных: `recurse` (рекурсивное слияние), `overwrite` (полная замена), `aggregate` (конкатенация списков).
- **`ext_pillar`**: Механизм динамической загрузки Pillar данных из внешних источников (Vault, Consul, MySQL, Git, JSON, YAML files) в момент компиляции на мастере.
- **Pillar Cache**: Кэш скомпилированных Pillar данных на мастере, ускоряющий повторную компиляцию.
- **`pillar_opts`**: Параметр, включающий доступ к конфигурации мастера через Pillar (`opts`).
- **`pillar_safe_render_error`**: Параметр, включающий безопасный рендеринг Pillar с обработкой ошибок.
- **Pillar Environment**: Окружение Pillar, определяющее какие pillar_roots использовать для конкретного миньона.
- **`pillarenv`**: Параметр, явно указывающий окружение Pillar для команды.

---

## Основные концепции

### Иерархия приоритетов Pillar

Данные Pillar разрешаются в следующем порядке (от низшего к высшему):

1. **defaults.yaml** в formula (最低优先级)
2. **pillar_roots/base/** — общий Pillar для всех окружений
3. **pillar_roots/{env}/** — Pillar для конкретного окружения (dev/staging/prod)
4. **ext_pillar** — внешние источники (Vault, Consul, MySQL)
5. **Pillar через CLI** — `pillar='{...}'` в команде (最高优先级)

### Стратегии слияния

| Стратегия | Описание | Пример |
|:---|:---|:---|
| `recurse` | Рекурсивное слияние словарей | `{'a': {'b': 1}}` + `{'a': {'c': 2}}` → `{'a': {'b': 1, 'c': 2}}` |
| `overwrite` | Полная замена | `{'a': 1}` + `{'a': 2}` → `{'a': 2}` |
| `aggregate` | Конкатенация списков | `{'a': [1]}` + `{'a': [2]}` → `{'a': [1, 2]}` |

### Порядок ext_pillar

ext_pillar обрабатываются последовательно. Последний источник перезаписывает предыдущий для одинаковых ключей:

```yaml
ext_pillar:
  - vault:                    # Первый источник
      url: http://vault:8200
      token: ...
  - mysql:                    # Второй источник
      query: "SELECT * FROM pillar"
  - yaml:                     # Третий источник
      - /srv/pillar/local.yaml
```

---

## Практические сценарии

### 1. Стратегии слияния (pillar_source_merging)

```yaml
# /etc/salt/master
pillar_source_merging: recurse
```

**Пример recurse:**

```yaml
# pillar_roots/base/webserver/init.sls
nginx:
  worker_processes: 4
  worker_connections: 1024

# pillar_roots/production/webserver/init.sls
nginx:
  worker_processes: 8
  ssl: True

# Результат (recurse):
nginx:
  worker_processes: 8   # Переопределено production
  worker_connections: 1024  # Сохранено из base
  ssl: True  # Добавлено из production
```

**Пример aggregate:**

```yaml
# pillar_source_merging: aggregate

# pillar_roots/base/packages/init.sls
packages:
  - vim
  - curl

# pillar_roots/production/packages/init.sls
packages:
  - nginx
  - postgresql

# Результат (aggregate):
packages:
  - vim
  - curl
  - nginx
  - postgresql
```

### 2. Ext_pillar комбинации

**Vault + MySQL:**

```yaml
# /etc/salt/master
ext_pillar:
  - vault:
      url: http://vault.example.com:8200
      token: s.xxxxx
      mount: secret
      path: salt/{minion}
  - mysql:
      host: db.example.com
      user: salt
      pass: secret
      db: salt_pillar
      query: "SELECT data FROM pillars WHERE minion_id = '{minion}'"
      as_json: True
```

**Consul + Git:**

```yaml
ext_pillar:
  - consul:
      consul_url: http://consul.example.com:8500
      consul_token: xxxxx
      pillar_path: salt/pillar
  - git:
      - master https://github.com/org/pillar.git
        - root: pillar
        - env: saltenv
```

### 3. Pillar Cache

```yaml
# /etc/salt/master
pillar_cache: True
pillar_cache_backend: diskcache
pillar_cache_ttl: 3600  # 1 час

# Кэш хранится в /var/cache/salt/master/pillar_cache/
```

```bash
# Очистка кэша
salt-run pillar.pillar_refresh

# Просмотр кэша
ls -la /var/cache/salt/master/pillar_cache/
```

### 4. Pillar через SDB

```yaml
# /etc/salt/master.d/sdb.conf
sdb:
  vault:
    driver: vault
    vault_url: http://vault:8200
    vault_token: s.xxxxx
```

```bash
# Сохранение
sdb.set vault secret/nginx password "supersecret"

# Получение
sdb.get vault secret/nginx/password
# → supersecret
```

**Использование в SLS:**

```yaml
nginx_password:
  file.managed:
    - name: /etc/nginx/.htpasswd
    - contents: |
        admin:{{ salt['vault.read_secret']('secret/nginx/password') }}
    - template: jinja
```

### 5. Pillar Environment Management

```yaml
# /etc/salt/master
pillar_roots:
  base:
    - /srv/pillar/base
  dev:
    - /srv/pillar/dev
  staging:
    - /srv/pillar/staging
  production:
    - /srv/pillar/production
```

```bash
# Применение с указанием pillarenv
salt '*' state.apply nginx pillarenv=production

# Просмотр Pillar для конкретного окружения
salt '*' pillar.items pillarenv=dev
```

### 6. Pillarargeting

```bash
# Все миньоны с ролью web
salt -I 'role:web' test.ping

# Все миньоны в production
salt -I 'environment:production' test.ping

# Составной Pillar-таргетинг
salt -C 'I@role:web and I@environment:production' test.ping
```

### 7. Безопасный рендеринг Pillar

```yaml
# /etc/salt/master
pillar_safe_render_error: True
```

**Пример безопасного рендеринга:**

```yaml
# Если в Pillar есть ошибка
pillar_example:
  safe_key: value
  broken_key: {{ invalid_jinja }}

# С pillar_safe_render_error: True
# Ошибка логируется, но Pillar продолжает компилироваться
# Без этого параметра — полный отказ компиляции
```

### 8. Просмотр и отладка Pillar

```bash
# Просмотр всего Pillar для миньона
salt '*' pillar.items

# Просмотр конкретного ключа
salt '*' pillar.get nginx

# Просмотр Pillar с verbose
salt '*' pillar.items --out=yaml

# Просмотр pillar_roots
salt-run pillar.roots

# Просмотр ext_pillar
salt-run pillar.pillar_refresh
salt '*' pillar.items | grep vault
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Pillar is not available` | Pillar не назначен миньону | Проверить `top.sls` в `pillar_roots` |
| `Ext_pillar not loading` | Неверный конфиг или credentials | Проверить `ext_pillar` в master config |
| `Pillar merge conflicts` | Неверная стратегия слияния | Изменить `pillar_source_merging` |
| `Vault pillar timeout` | Vault недоступен | Проверить `vault_url`, токен, сеть |
| `Pillar cache stale` | Кэш не обновлён | `salt-run pillar.pillar_refresh`, уменьшить `pillar_cache_ttl` |
| `Pillar rendering error` | Ошибка в Jinja-шаблоне | `pillar_safe_render_error: True`, проверить шаблон |
| `Pillar environment mismatch` | Неверный `pillarenv` | Проверить `pillar_roots` для окружения |

### Best practices

1. **Иерархия**: base → env → ext_pillar → CLI pillar.
2. **Слияние**: `recurse` для вложенных словарей, `aggregate` для списков.
3. **Кэширование**: Включайте `pillar_cache` для ускорения.
4. **Безопасность**: Храните секреты в Vault/SDB, не в plaintext.
5. **Версионирование**: Храните Pillar в Git, используйте ветвление.
6. **Тестирование**: Проверяйте `pillar.items` перед deploy.
7. **Мониторинг**: Настройте алертинг на проблемы Pillar.
8. **Окружения**: Используйте `pillarenv` для изоляции env.

### Версии и совместимость

| Версия Salt | Особенности Pillar |
|:---|:---|
| 3006 LTS | Стандартный ext_pillar, pillar_cache |
| 3007 STS | Улучшенное слияние, `pillar_safe_render_error` |
| 3008 LTS | Безопасный рендеринг, `SafeDict`/`SafeList` |

### См. также

- [Архитектура SaltStack](Architecture.md) — Pillar overview
- [Безопасность SaltStack](Security_Approaches.md) — Pillar encryption
- [Формулы SaltStack](Formulas.md) — Pillar в formulas
