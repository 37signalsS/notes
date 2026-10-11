# GitHub Pages: Статический хостинг и деплой

**Актуально для:** GitHub Pages, октябрь 2026 (source: workflow/GitHub Actions; `peaceiris/actions-gh-pages` устаревает; custom domains с ALPN; GitHub Pages из workflow); для GitHub Enterprise Server — 3.14+ (ограниченная поддержка)

GitHub Pages — это встроенный в GitHub статический хостинг для веб-сайтов (HTML/CSS/JS, документация, блоги на Jekyll). Сайт разворачывается из репозитория и доступен по адресу `https://{username}.github.io/{repo}` (для org — `https://{org}.github.io/{repo}`) или с кастомным доменом. С 2026 года GitHub Pages интегрирован с GitHub Actions: деплой статических артефактов (из workflow) стал основным способом, а не только из ветки `/docs` или `/root`.

## Определения

- **GitHub Pages**: Статический хостинг сайтов из репозитория GitHub. Доступен для public и private репозиториев (для private — только на Enterprise/Team планах).
- **Source**: Источник сайта — ветка/директория (legacy) или workflow (современный способ, recomended).
- **Build and Deployment**: Автоматическая сборка (Jekyll) и деплой при изменении source.
- **Custom Domain**: Кастомный домен (CNAME) с HTTPS через GitHub.
- **Jekyll**: Статический генератор сайтов, встроенный в Pages. Автоматически обрабатывает Markdown, шаблоны, плагины.
- **ALPN**: Механизм HTTPS для кастомных доменов — GitHub использует ALPN-сертификаты для быстрого выдачи TLS.
- **404 page**: Автоматически обслуживается страница `404.md` или `/404.html`.

## Архитектура и source

### Модели деплоя

| Source | Описание | Когда использовать |
|---|---|---|
| **Workflow (рекомендуется)** | Артефакт из `actions/upload-pages-artifact` деплоится через `actions/deploy-pages` | Любой static-сайт (React, Vue, Svelte, Jekyll, Hugo) |
| **Branch + `/(root)`** | Деплой из корня указанной ветки | Простые сайты без сборки |
| **Branch + `/docs`** | Деплой из директории `/docs` в ветке | Документация рядом с source code |
| **Jekyll (встроенный)** | GitHub автоматически сборает Jekyll-сайт | Документация на Markdown/Blog |

### Как это работает (Workflow source)

```text
GitHub Actions Workflow
    │
    1. actions/upload-pages-artifact (собранные файлы → artifact)
    │
    2. actions/deploy-pages (загрузка артефакта в Pages infrastructure)
    │
    3. GitHub Pages serves: https://{user}.github.io/{repo}/
    │
    4. Custom domain (опционально) → ALPN TLS → CAA запись
```

## Практические сценарии

### Сценарий 1: Деплой статического сайта через GitHub Actions

**Предварительные требования**: Включённый GitHub Pages в Settings → Pages → Build and deployment → Source: GitHub Actions.

```yaml
name: Deploy to GitHub Pages
on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages-${{ github.ref }}
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - name: Setup Node.js
        uses: actions/setup-node@v7
        with:
          node-version: '24'
          cache: 'npm'

      - name: Install and build
        run: |
          npm ci
          npm run build      # → dist/

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: dist/

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: github-pages  # встроенное окружение для Pages
    steps:
      - name: Deploy to Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- **Валидация**: в UI Settings → Pages статус `Built and deployed`; URL `https://{username}.github.io/{repo}` доступен через 1–2 минуты.
- **`environment: github-pages`**: встроенное environment с защитой от перезаписи; `concurrency` предотвращает гонки.

### Сценарий 2: Настройка кастомного домена

```bash
# 1. Добавить кастомный домен через API
gh api -X PUT /repos/{owner}/{repo} \
  -f homepage="https://www.example.com" \
  -f "source={'branch':'gh-pages','path':'/'}"

# 2. Или через UI: Settings → Pages → Custom domain → https://example.com
#    GitHub автоматически создаст ALPN-сертификат

# 3. DNS-записи для apex/root домена
#    - A-record → 185.199.108.153, 185.199.109.153, 185.199.110.153, 185.199.111.153
#    - AAAA-record → 2610:10::1, 2610:10::2 (опционально)

# 4. CNAME для поддомена (www, docs)
#    docs.example.com CNAME → {username}.github.io.
```

**Файл `CNAME` в корне сайта**:
```text
docs.example.com
```

- **ALPN**: GitHub поддерживает ALPN-сертификаты — домен сразу работает с HTTPS, без ожидания DNS-пропагации на 24–48 часов.
- **Enforced HTTPS**: включается автоматически при добавлении кастомного домена.

### Сценарий 3: Jekyll (встроенный static generator)

Для простых сайтов на Markdown без собственного workflow:

```yaml
# _config.yml (корень Jekyll)
title: My Project
description: Documentation
theme: minima  # встроенная Jekyll-тема GitHub
plugins:
  - jekyll-feed     # RSS
  - jemoji          # эмодзи

collections:
  docs:
    output: true
    permalink: /docs/:path/
```

GitHub Pages автоматически сборает Jekyll-сайт при пуше в source-ветку.

### Сценарий 4: 404 page и перенаправления

```markdown
<!-- 404.md или /docs/404.html -->
---
permalink: /404.html
---

# Page not found

The page you're looking for doesn't exist.

<a href="/">Go home</a>
```

Для перенаправлений через `index.html` в корне:

```html
<!-- index.html в корне → перенаправление на docs/ -->
<!DOCTYPE html>
<html>
  <head>
    <meta http-equiv="refresh" content="0; url=/docs/">
  </head>
</html>
```

### Сценарий 5: Настройки видимости

```bash
# Сделать Pages публичным для private репозитория
gh api -X PUT /repos/{owner}/{repo} \
  -f "visibility=public"

# Или через UI: Settings → Pages → Visibility
# Options: Public (всем), Private (только с доступом к репо)
```

## Команды и API-операции

### GitHub CLI

| Команда | Описание |
|---|---|
| `gh api .../pages` | Получить информацию о Pages |
| `gh api -X PUT .../pages` | Включить/обновить Pages |
| `gh api -X DELETE .../pages` | Отключить Pages |

### API

| Операция | Endpoint |
|---|---|
| Получить Pages | `GET /repos/{owner}/{repo}/pages` |
| Создать/обновить Pages | `POST/PUT /repos/{owner}/{repo}/pages` |
| Удалить Pages | `DELETE /repos/{owner}/{repo}/pages` |
| Создать deployment | `POST /repos/{owner}/{repo}/pages/deployments` |
| Проверить статус | `GET /repos/{owner}/{repo}/pages/health` |
| Список доменов | `GET /repos/{owner}/{repo}/pages/domains` |
| Добавить домен | `POST /repos/{owner}/{repo}/pages/domains` |

### CLI для управления

```bash
# Включить Pages из workflow source
gh api -X POST /repos/{owner}/{repo}/pages \
  -f source='{"branch":"main","path":"/"}'

# Проверить статус
gh api /repos/{owner}/{repo}/pages --jq '.status'

# Добавить кастомный домен
gh api -X POST /repos/{owner}/{repo}/pages/domains \
  -f domain="docs.example.com"

# Удалить Pages
gh api -X DELETE /repos/{owner}/{repo}/pages
```

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| `404` после деплоя | Source не включён или артефакт пустой | Settings → Pages → включить source; проверить путь к артефакту |
| Домен не HTTPS | ALPN-сертификат не выдан | Подождать 1–2 мин; проверить DNS; включить Enforce HTTPS |
| `pages build and deployment failed` | Ошибка в workflow (upload-pages-artifact не нашёл файлы) | Проверить `path: dist/`; убедиться, что build успешен |
| Старый кэш | CDN не обновился | Подождать 1 мин; `hard refresh`; в крайнем случае — disable/re-enable Pages |
| `Domain name not found` | DNS не настроен | Проверить A/AAAA/CNAME записи; использовать `dig` для проверки |
| Private repo Pages недоступен | Нет доступа у зрителя | Pages для private репо — только с доступом к репо |

## Лучшие практики

1. **Workflow source, а не branch source**: используйте `actions/deploy-pages@v4` — это надёжнее и поддерживает production workflows.
2. **Concurrency для Pages**: `concurrency: group: pages-${{ github.ref }}` предотвращает одновременные деплои.
3. **ALPN для custom доменов**: используйте ALPN вместо DNS-проверки — сертификат выдаётся мгновенно.
4. **404 page**: всегда добавляйте `404.html` для better UX.
5. **Private Pages**: для private репо включайте `visibility: public` на Pages, а не на весь репозиторий — сайт доступен всем, а исходный код — только с доступом.
6. **Jekyll plugin limitations**: GitHub Pages поддерживает только whitelist плагинов. Для custom плагинов используйте standalone Jekyll с workflow.
7. **Caching для CDN**: GitHub Pages CDN кэширует. Добавляйте хеш к assets (`/static/main.abc123.css`) для сброса кэша.
8. **Enforce HTTPS**: всегда включайте — GitHub автоматически перенаправляет HTTP → HTTPS.

## Дополнительная информация

- **[Release Management](./Release_Management.md)** — публикация релизов и артефакактов.
- **[GitHub CLI](./github_cli.md)** — `gh release create`, `gh api` для Pages.
- **[GitHub Packages и GHCR](./github_packages_ghcr.md)** — публикация пакетов рядом с Pages.
- **Официальная документация**: [GitHub Pages](https://docs.github.com/en/pages), [Configuring a publish source](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).
