# Превью- и ephemeral-окружения для фронтенда

## Определения

- **Preview Environment (Review App)** — временное, изолированное окружение, автоматически поднимаемое для конкретной ветки/MR и уничтожаемое при её закрытии.
- **Ephemeral Environment** — окружение, существующее ровно на время жизни задачи/ветки (не перманентное).
- **Dynamic Environment** — окружение с динамически выделяемым URL/порт, управляемое пайплайном.
- **Subdomain routing** — маршрутизация превью по уникальному поддомену (например, `mr-123.app.example.com`).
- **On-stop cleanup** — скрипт/хук, удаляющий окружение при закрытии MR.

---

## Основные концепции

### Зачем нужны превью-окружения
Дают возможность проверить визуальный регрессионный тест, LHCI, e2e и ручной QA именно на коде ветки до мержа в `main`. Это сокращает цикл обратной связи и ловит проблемы, невидимые в юнит-тестах.

### Жизненный цикл
1. **Create:** при открытии/обновлении MR поднимается окружение (статика в каталог или SSR-процесс на выделенном порту).
2. **Update:** при каждом пуше — пересборка и обновление.
3. **Destroy:** при закрытии/мерже MR — `on-stop` удаляет ресурсы.

### Изоляция и именование
- Имя/порт окружения однозначно привязано к MR (`mr-123`), чтобы не конфликтовать.
- Для SSR используется изолированный процесс (порт) за nginx-роутингом по subdomain.
- Данные: либо общий staging-бэкенд (read-only/replica), либо выделенный набор с seed-данными.

### Стоимость и очистка
Превью могут накапливаться. Обязателен `on-stop` cleanup и авто-удаление «висячих» окружений по возрасту (например, старше 7 дней).

---

## Практические сценарии

### Сценарий 1: GitLab Dynamic Environment (статика)
```yaml
preview:
  stage: deploy
  environment:
    name: review/mr-$CI_MERGE_REQUEST_IID
    url: https://mr-$CI_MERGE_REQUEST_IID.app.example.com
    on_stop: stop_preview
  script:
    - npm ci && npm run build
    - rsync -az dist/ deploy@preview:/srv/preview/mr-$CI_MERGE_REQUEST_IID/
  rules:
    - if: $CI_MERGE_REQUEST_ID

stop_preview:
  stage: deploy
  script:
    - ssh deploy@preview "rm -rf /srv/preview/mr-$CI_MERGE_REQUEST_IID"
  environment:
    name: review/mr-$CI_MERGE_REQUEST_IID
    action: stop
  rules:
    - if: $CI_MERGE_REQUEST_ID
      when: manual
```

### Сценарий 2: Превью для SSR (изолированный процесс + nginx subdomain)
```bash
# Запуск SSR на уникальном порту для MR
PORT=$(( 4000 + $CI_MERGE_REQUEST_IID % 1000 ))
APP_PORT=$PORT npm run start -- -p $PORT &
# nginx роутит поддомен на этот порт (конфиг генерируется в пайплайне)
cat > /etc/nginx/conf.d/mr-$CI_MERGE_REQUEST_IID.conf <<EOF
server {
    server_name mr-$CI_MERGE_REQUEST_IID.app.example.com;
    location / { proxy_pass http://127.0.0.1:$PORT; }
}
EOF
nginx -s reload
```

### Сценарий 3: Интеграция с визуальными тестами
```yaml
visual_on_preview:
  stage: test
  script:
    - npx playwright test --grep @visual --base-url https://mr-$CI_MERGE_REQUEST_IID.app.example.com
  artifacts:
    when: on_failure
    paths: [playwright-report/]
```

### Сценарий 4: Авто-очистка «висячих» окружений
```bash
# Cron/раннер: удаляем превью старше 7 дней
ssh deploy@preview "find /srv/preview -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +"
```

---

## Дополнительная информация

### Лучшие практики
1. URL превью должен быть предсказуем и привязан к MR (`mr-<iid>`).
2. Всегда определяйте `on_stop` — иначе окружения будут копиться.
3. Для SSR изолируйте порты и не используйте общую БД с продом (только staging/replica/seed).
4. Запускайте на превью те же проверки, что в `main` (LHCI, visual, e2e), но с меньшим числом прогонов.
5. Ограничивайте число одновременных превью (квота по портам/диску).

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Окружения копятся | Нет `on_stop` | Обязательный `action: stop` + cron-очистка |
| Конфликт портов SSR | Фиксированный порт | Динамический порт от MR IID |
| Превью падает | Нет изоляции БД | Seed-данные / staging-replica |
| Долгий подъём | Полная пересборка | Кэш зависимостей + affected (см. monorepo) |

### См. также
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — сборка, деплой статики, визуальные тесты.
- **[Деплой SSR/SSG/ISR](./ssr_ssg_deployment.md)** — как поднять SSR-процесс для превью.
- **[Feature flags в доставке фронтенда](./feature_flags_frontend.md)** — per-preview флаги.
- **[Стратегии деплоя](../Core_Concepts/deployment_strategies.md)** — связь с canary/blue-green.
