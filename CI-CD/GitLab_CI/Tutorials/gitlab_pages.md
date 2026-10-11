# GitLab Pages в CI/CD пайплайнах

**Актуально для:** GitLab 17.x–19.x

> **Примечание:** Основная теория GitLab Pages, DNS и Let's Encrypt описана в официальной документации GitLab: **[GitLab Pages — официальная документация](https://docs.gitlab.com/user/project/pages/)**. Это руководство фокусируется на практической настройке Pages в production среде с CI/CD.

## Определения

| Термин | Описание |
|:---|:---|
| **GitLab Pages** | Встроенная функция GitLab для размещения статических сайтов напрямую из репозитория. Не поддерживает динамическую обработку на стороне сервера (PHP, ASP и т.п.). |
| **Статический сайт** | Сайт, состоящий из готовых HTML-, CSS-, JS- и медиа-файлов, который не требует серверной генерации контента при каждом запросе. |
| **Артефакт (artifact)** | Файлы, созданные во время выполнения задачи CI/CD и сохраняемые для последующих стадий или для Pages. |
| **`public/`** | Каталог, из которого GitLab Pages разворачивает сайт по умолчанию. Любой job с `artifacts:paths: [public]` и свойством `pages` триггерит деплой. |
| **`pages` (job property)** | Свойство задачи, указывающее GitLab, что результат необходимо опубликовать через GitLab Pages. Принимает тип `Boolean` (`true`) или `Map`. |
| **Runner** | Исполнитель задач CI/CD. Для Pages требуется Runner с доступом в интернет (TCP 443) для отправки артефактов на Pages-сервер. |
| **Custom domain** | Пользовательский домен (например, `docs.example.com`), привязанный к Pages-сайту вместо домена по умолчанию `<namespace>.gitlab.io`. |
| **Parallel deployment** | Дополнительное развёртывание Pages с непустым `path_prefix`, доступное через URI `/project/-/pages/:path_prefix`. По умолчанию удаляется через 24 часа. |

## Как работает GitLab Pages

GitLab Pages использует встроенный CI/CD для автоматической сборки и публикации статических сайтов. Жизненный цикл деплоя состоит из трёх этапов:

1. **Сборка (build)** — задача компилирует исходники сайта (Hugo, Jekyll, Docusaurus, MkDocs или кастомный сборщик) и помещает результат в каталог `public/`.
2. **Передача артефактов** — GitLab сохраняет содержимое `public/` как артефакт задачи. Если в задаче указано свойство `pages`, GitLab помечает артефакт для публикации.
3. **Публикация** — GitLab Pages-сервер получает артефакт и делает сайт доступным по URL:
   - По умолчанию: `https://<namespace>.gitlab.io/<project>/`
   - С custom domain: `https://<custom-domain>` (привязанному в настройках проекта)

### Ключевые ограничения

- **Одна задача Pages на пайплайн.** Несколько задач с `pages: true` с одинаковым `path_prefix` приводят к тому, что deploying будет последняя завершённая задача.
- **Только статический контент.** Динамическая обработка (PHP, ASP, серверные шаблоны) не поддерживается.
- **Размер артефакта.** Ограничен настройками инстанса (по умолчанию обычно 1–5 ГБ). Для больших сайтов используйте incremental build или разбейте контент на несколько проектов.
- **Время сборки.** Pipeline для Pages должен укладываться в общий таймаут проекта/инстанса.

## Предварительные требования

### Обязательные

- GitLab-проект с включённым **Pages** (**Settings > General > Visibility, project features, permissions > Pages**).
- Роль **Maintainer** или **Owner** в проекте для настройки Pages.
- Доступный Runner с поддержкой нужной платформы (Linux, Windows, macOS) и доступом в интернет (TCP 443) для отправки артефактов.
- Репозиторий с исходниками статического сайта или конфигурацией SSG.

### Для custom domain (опционально)

- Зарегистрированный домен или поддомен.
- Возможность редактирования DNS-записей (A, AAAA или CNAME).
- Для SSL: автоматический provisioning через Let's Encrypt (требует, чтобы инстанс GitLab имел доступ к домену из интернета) или пользовательский SSL-сертификат, загруженный в **Settings > Pages > Certificates**.

### Для self-hosted инстансов

- Администратор должен настроить Pages-сервер (см. [администрирование GitLab Pages](https://docs.gitlab.com/administration/pages/)).
- Pages-демон должен быть запущен и доступен из GitLab и из интернета (если нужны custom domains).
- Для object storage: настроен S3-совместимый бэкенд или сетевой хранилище для артефактов Pages.

## Практические сценарии

### Сценарий 1: Базовый Pages deployment

```yaml
stages:
  - build
  - deploy

variables:
  GIT_STRATEGY: clone

build:
  stage: build
  image: node:21-slim
  script:
    - npm install
    - npm run build
  artifacts:
    paths:
      - public/
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

pages:
  stage: deploy
  image: alpine:3.21
  script:
    - mkdir -p public
    - cp -r build/* public/
  artifacts:
    paths:
      - public/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Примечание:** Задача `pages` копирует артефакт из `build/` в `public/`, потому что артефакты между задачами передаются по каноническому пути артефакта (по умолчанию `public/`). Если в `build` артефакт уже находится в `public/`, задача `pages` может быть упрощена до пустой — GitLab автоматически использует артефакт предыдущей задачи.

### Сценарий 2: Hugo Static Site Generator

```yaml
stages:
  - build
  - deploy

variables:
  GIT_STRATEGY: clone

build-hugo:
  stage: build
  image: hugomods/hugo:0.134.0
  script:
    - hugo --minify --baseURL "https://$CI_PROJECT_NAMESPACE.gitlab.io/$CI_PROJECT_NAME"
  artifacts:
    paths:
      - public/
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

pages:
  stage: deploy
  image: alpine:3.21
  script:
    - mkdir -p public
    - cp -r ../build-hugo/public/* public/
  artifacts:
    paths:
      - public/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 3: Jekyll Documentation Site

```yaml
stages:
  - build
  - deploy

variables:
  GIT_STRATEGY: clone
  LC_ALL: "C.UTF-8"
  LANG: "C.UTF-8"

build-jekyll:
  stage: build
  image: ruby:3.3-slim
  before_script:
    - gem install bundler jekyll
    - bundle install
  script:
    - bundle exec jekyll build --destination public/ --baseurl "/$CI_PROJECT_NAME"
  artifacts:
    paths:
      - public/
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

pages:
  stage: deploy
  image: alpine:3.21
  script:
    - mkdir -p public
    - cp -r ../build-jekyll/public/* public/
  artifacts:
    paths:
      - public/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 4: Docusaurus Documentation

```yaml
stages:
  - build
  - deploy

variables:
  GIT_STRATEGY: clone
  NODE_OPTIONS: "--max-old-space-size=4096"

build-docusaurus:
  stage: build
  image: node:21-slim
  cache:
    paths:
      - node_modules/
  script:
    - npm install
    - npm run build
  artifacts:
    paths:
      - build/
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

pages:
  stage: deploy
  image: alpine:3.21
  script:
    - mkdir -p public
    - cp -r ../build-docusaurus/build/* public/
  artifacts:
    paths:
      - public/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 5: MkDocs Documentation

```yaml
stages:
  - build
  - deploy

variables:
  GIT_STRATEGY: clone

build-mkdocs:
  stage: build
  image: python:3.13-slim
  before_script:
    - pip install mkdocs mkdocs-material
  script:
    - mkdocs build --site-dir public/
  artifacts:
    paths:
      - public/
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

pages:
  stage: deploy
  image: alpine:3.21
  script:
    - mkdir -p public
    - cp -r ../build-mkdocs/public/* public/
  artifacts:
    paths:
      - public/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 6: Custom Domain с Let's Encrypt

```yaml
stages:
  - deploy

variables:
  GIT_STRATEGY: clone

pages:
  stage: deploy
  image: alpine:3.21
  script:
    - |
      # Создание _redirects файла для custom domain
      cat > public/_redirects <<EOF
      # Redirects для custom domain
      / https://docs.example.com/:splat 301
      EOF
    - |
      # Создание CNAME файла
      echo "docs.example.com" > public/CNAME
  artifacts:
    paths:
      - public/
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Настройка в GitLab UI:**
1. **Settings > Pages > Pages domains**
2. Добавьте custom domain: `docs.example.com`
3. Включите **Auto provision SSL certificate** (Let's Encrypt)
4. Добавьте DNS record: `CNAME docs.example.com -> <group>.gitlab.io`

## Валидация и проверка

1. **Pages URL:** Откройте `https://<namespace>.gitlab.io/<project>` — должен отображаться сайт
2. **Custom Domain:** Откройте `https://docs.example.com` — должен отображаться сайт с SSL
3. **SSL Certificate:** Проверьте сертификат — должен быть валидным (Let's Encrypt)
4. **Artifacts:** Проверьте **CI/CD > Jobs > pages > Artifacts** — должны отображаться файлы
5. **Build Logs:** Проверьте логи сборки — не должно быть ошибок

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Pages not accessible** | Артефакты не загружены или `public/` пустой | Проверьте логи задачи `pages` и наличие файлов в `public/` |
| **404 on custom domain** | DNS не настроен или CNAME неверен | Проверьте DNS record и CNAME файл в `public/` |
| **SSL certificate error** | Let's Encrypt не может проверить домен | Проверьте DNS propagation и доступность домена |
| **Build failed** | Ошибка в генераторе сайта | Проверьте логи сборки (Hugo/Jekyll/Docusaurus) |
| **Access denied** | Pages настроен как private | Измените настройки доступа в **Settings > Pages** |
| **Cache not working** | Кеш не настроен или ключ неверный | Проверьте настройки кеша в `.gitlab-ci.yml` |
| **Large site timeout** | Слишком большой сайт | Используйте incremental build или уменьшите размер сайта |

## Лучшие практики (Best Practices)

**Безопасность:**
- Используйте HTTPS для всех Pages (Let's Encrypt или custom SSL)
- Ограничьте доступ к sensitive Pages через `access_control`
- Используйте custom domains вместо wildcard для production
- Включите HSTS для custom domains
- Регулярно обновляйте зависимости генераторов сайтов

**Производительность:**
- Используйте CDN для static assets (GitLab CDN для Pages)
- Минифицируйте CSS/JS (Hugo, Docusaurus имеют built-in оптимизацию)
- Используйте image compression (WebP, AVIF)
- Кешируйте артефакты между запусками
- Используйте incremental builds для больших сайтов

**Надёжность:**
- Используйте `access_control` для private документации
- Настройте алерты на недоступность Pages
- Используйте version control для контента Pages
- Документируйте процесс обновления документации
- Используйте MR workflow для обновления документации

## Особенности и ограничения

- **Одна задача Pages на pipeline.** GitLab позволяет только одну задачу с `pages: true` на один pipeline с одинаковым `path_prefix`. Последняя завершённая задача перезаписывает предыдущие.
- **Parallel deployments.** GitLab 17.x+ поддерживает параллельные деплойменты через `path_prefix`. Они автоматически удаляются через 24 часа, если не установлено `pages.expire_in: never`. Используются для preview-окружений в merge request.
- **Размер артефакта.** Ограничен конфигурацией инстанса. Для сайтов >1 ГБ используйте object storage на стороне администратора или разбейте контент.
- **Self-hosted vs GitLab.com.** На GitLab.com Pages предоставляются на инфраструктуре GitLab. На self-hosted инстансах Pages могут быть отключены по умолчанию и требуют включения администратором.
- **Dynamic content.** Pages не поддерживает server-side rendering, PHP, ASP или другие динамические платформы. Для динамического контента используйте отдельный application server.
- **Custom domain SSL.** Let's Encrypt требует, чтобы домен был доступен из интернета для прохождения challenge. Для внутренних доменов используйте пользовательские сертификаты.
- **Branch vs Tag deployments.** По умолчанию Pages деплоится только из веток. Для тегов добавьте соответствующее правило в `rules` или `only/except`.

## Очистка

```bash
# Удаление старого Pages deployment
glab api projects/$PROJECT_ID/jobs | jq -r '.[] | select(.name == "pages") | .id' | \
  while read job_id; do
    glab api projects/$PROJECT_ID/jobs/$job_id -X DELETE
  done
```

**Примечание:** Требует установленного и аутентифицированного GitLab CLI (`glab`).

## Дополнительная информация

### Смотрите также

- **[GitLab Pages — официальная документация](https://docs.gitlab.com/user/project/pages/)** — теория, DNS, Let's Encrypt, настройка инстанса
- **[Docusaurus Documentation](https://docusaurus.io/)** — генератор документации
- **[Hugo Documentation](https://gohugo.io/)** — генератор статических сайтов
- **[MkDocs Documentation](https://www.mkdocs.org/)** — генератор документации
