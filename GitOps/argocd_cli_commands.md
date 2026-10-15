# Argo CD CLI: справочник команд

**Актуально для:** Argo CD 3.5.x

## Определения

**Argo CD** — GitOps-оператор для Kubernetes: непрерывно сверяет состояние кластера с декларативным источником в Git и автоматически приводит кластер к желаемому состоянию (reconciliation).

**argocd CLI** — клиент управления Argo CD: аутентификация, создание и синхронизация приложений, переопределения, диагностика. Общается с API server Argo CD; для работы требуется доступ к серверу (Ingress/port-forward) и учётные данные.

**Application (App)** — CRD, описывающий один источник (Git-репозиторий, путь, Helm/Kustomize) и назначение (кластер, namespace).

**AppProject** — логическая изоляция приложений: ограничения по источникам (`sourceRepos`), назначениям (`destinations`), ролям RBAC и окнам синхронизации.

## Основные концепции

### Модель работы CLI

1. **Аутентификация:** `argocd login <server>` — токен сохраняется в `~/.argocd/config`. Начальный пароль admin — в секрете `argocd-initial-admin-secret` (namespace `argocd`).
2. **Декларативность:** приложение создаётся один раз (`app create`); дальнейшие изменения — в Git, Argo CD сам их подхватывает.
3. **Синхронизация:** `app sync` применяет различия между Git и кластером; `--prune` удаляет ресурсы, удалённые из Git.
4. **Drift:** ручные правки в кластере обнаруживаются как `OutOfSync` (`app diff`); штатный путь исправления — коммит в Git, а не правка в кластере.

## Практические сценарии

### Аутентификация

```bash
# Первый вход: начальный пароль admin из секрета
argocd login argocd.example.com --username admin \
  --password $(kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='{.data.password}' | base64 -d)
```

### Управление приложениями

```bash
# Все приложения со статусом синхронизации и здоровья
argocd app list

# Детали приложения; --refresh — принудительное обновление манифестов из Git (в обход кэша)
argocd app get myapp --refresh

# Что изменится при синхронизации (drift Git vs кластер)
argocd app diff myapp

# Синхронизация с удалением ресурсов, исчезнувших из Git
argocd app sync myapp --prune

# Откат к ревизии 3 из истории приложения
argocd app rollback myapp 3

# Все ресурсы, управляемые приложением
argocd app resources myapp

# Ожидание синхронизированного и здорового состояния (CI-гейт)
argocd app wait myapp --sync --health --timeout 120

# Создание приложения с автосинхронизацией
argocd app create myapp \
  --repo https://github.com/org/repo \
  --path k8s/prod \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default \
  --sync-policy automated

# Удаление объекта Application без удаления ресурсов Kubernetes
argocd app delete myapp --cascade=false
```

### Переопределения и патчи (без правки Git)

```bash
# Переопределить образ для Kustomize-приложения
argocd app set myapp --kustomize-image myapp=myregistry/myapp:v1.2.3

# Переопределить Helm-значения на лету
argocd app set myapp --helm-set image.tag=v2 --helm-set replicaCount=3

# Произвольные параметры Kustomize/Helm
argocd app set myapp -p key=val -p env=prod

# Merge-патч спецификации (например, смена targetRevision)
argocd app patch myapp --patch '{"spec":{"source":{"targetRevision":"v2.1"}}}' --type merge

# Prune и Server-Side Apply (SSA решает конфликты apply больших CRD)
argocd app set myapp --sync-option Prune=true --sync-option ServerSideApply=true

# Синхронизация только одного ресурса
argocd app sync myapp --resource apps:Deployment:<name>
```

> **Важно:** переопределения (`--helm-set`, `-p`, `--kustomize-image`) вызывают дрейф от источника в Git — кластер расходится с эталоном. Для аудита и воспроизводимости предпочтительнее overlay/патч в Git; CLI-переопределения — для разовой отладки.

### Кластеры и репозитории

```bash
# Зарегистрировать внешний кластер по контексту kubeconfig
argocd cluster add my-k8s-context

# Все кластеры под управлением Argo CD
argocd cluster list

# Приватный HTTPS-репозиторий (для SSH — --ssh-private-key-path)
argocd repo add https://git.example.com/repo.git --username <id> --password $TOKEN
```

### Проекты, RBAC и окна синхронизации

```bash
# Проект с ограничениями по источнику и назначению
argocd proj create myproject \
  --description 'Production apps' \
  --dest 'https://kubernetes.default.svc,prod' \
  --src 'https://github.com/org/*'

# Deny-окно: заморозка деплоев в нерабочее время (расписание cron)
argocd proj windows add <name> --kind deny --schedule '0 0 * * *' --duration 8h --applications '*'
```

### ApplicationSet, операции, отладка

```bash
# ApplicationSet и сгенерированные дочерние приложения
argocd appset list && argocd appset get <name> -o yaml

# Сравнение отрендеренных манифестов с кластером до синхронизации
argocd app manifests myapp | kubectl diff -f -

# Отмена зависшей синхронизации (застряла на хуке или ожидающем ресурсе)
argocd app terminate-op myapp

# Rollout restart Deployment через resource-действия Argo CD
argocd app actions run myapp restart --kind Deployment --resource-name <name>
```

### Резервная копия и DR

```bash
# Экспорт всех приложений, проектов и настроек (включая секреты кластеров)
argocd admin export -n argocd > argo-backup.yaml

# Восстановление
argocd admin import -n argocd - < argo-backup.yaml
```

## Устранение неполадок

| Симптом | Причина | Решение |
|:---|:---|:---|
| `argocd app rollback` «откатился», но вернулся обратно | Включена автосинхронизация: следующий цикл реконсиляции видит расхождение Git != кластер и возвращает версию из Git | Штатный путь — `git revert` в Git; откат через API — только временно, с `--sync-policy none` |
| Вечный `OutOfSync` после `app set --helm-set` | CLI-переопределение не зафиксировано в Git | Перенести изменение в Git или убрать переопределение (`argocd app set myapp --helm-set image.tag-`) |
| Синхронизация зависла | Хук или ожидающий ресурс не завершаются | `argocd app terminate-op <name>`, затем `argocd app get <name> --refresh` |
| Argo CD не видит новую версию чарта/образа | Кэш репозитория, интервал опроса | `argocd app get <name> --refresh`; вебхук реестра/репозитория на API Argo CD |
| `argocd app wait` таймаутит | Ресурс не достиг health/sync (например, `Progressing`) | `argocd app resources <name>` — какие ресурсы не готовы; детали в выводе ошибки |

## Лучшие практики

- **`git revert` вместо `app rollback`:** откат через Git сохраняет историю и работает при автосинхронизации; `app rollback` — аварийный инструмент.
- **Переопределения — только для отладки:** `--helm-set`/`-p`/`--kustomize-image` размывают источник истины; в production — overlay в Git.
- **Deny-окна для freeze-периодов:** `proj windows add` защищает нерабочее время от случайных синхронизаций.
- **CI-гейт на `app wait`:** `argocd app wait <name> --sync --health --timeout 120` в пайплайне подтверждает успешный деплой перед следующим шагом.
- **`--cascade=false` при удалении:** позволяет убрать Application из Argo CD, оставив ресурсы в кластере (миграция, передача управления).

## Дополнительная информация

- Концепции GitOps и конвейер: **[GitOps: обзор](./GitOps_overview.md)**, **[Пример GitOps-пайплайна](./gitops_pipeline_example.md)**
- Argo CD vs Flux: **[Сравнение манифестов](./argo_vs_flux_manifests.md)**
- Аудит и история синхронизаций: **[Аудит GitOps](./Concepts/audit_logs.md)**
- Мультикластерные паттерны: **[Multi-cluster patterns](./Concepts/multi_cluster_patterns.md)**
- Официальная документация CLI: [argo-cd.readthedocs.io — Commands](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/)
