# Vault Integration with GitLab CI on Kubernetes

This document outlines the process of installing HashiCorp Vault in a Kubernetes cluster and integrating it with GitLab CI for secret management.

## Установка Vault в кластер и настройка его для интеграции с GitLab

Установка Vault и все манипуляции проводятся на хосте `master-1` с правами `root`.

Так как Vault использует переменные окружения для конфигурации, нам нужен какой-то проект. Поэтому сделайте fork репозитория `https://gitlab.slurm.io/edu/ci-cd/cicd-app` или используйте уже сделанный ранее. Шаги из практики к этой теме не будут влиять на выполнение других этапов CI/CD, поэтому можете просто дополнить уже готовый файл `.gitlab-ci.yml` новыми этапами по ходу практики.

А начнём мы в терминале и добавим там в Helm репозиторий Banzai Cloud:

```bash
helm repo add banzaicloud-stable https://kubernetes-charts.banzaicloud.com
```

Создаём отдельный namespace для оператора:

```bash
kubectl create namespace vault-infra
kubectl label namespace vault-infra name=vault-infra
```

И устанавливаем оператор версии не выше 1.2.0 в этот namespace (на это потребуется 1-4 минуты):

```bash
helm upgrade --install vault-operator banzaicloud-stable/vault-operator --namespace vault-infra --version 1.2.0 --wait
```

Далее нам понадобятся материалы к курсу, скопируем репозиторий на `master-1`:

```bash
git clone git@gitlab.slurm.io:edu/ci-cd/cicd-new.git
cd cicd-new/practice/13.security
```

Не забудьте изменить в файле `cr.yaml` значение переменной `host: vault.s<Номер логина>.edu.slurm.io` на ваш собственный номер логина:

```bash
vim operator/cr.yaml
```

Далее применяем манифесты в кластер для того, чтобы оператор создал нам Vault с нужными параметрами:

```bash
kubectl apply -f operator/rbac.yaml
kubectl apply -f operator/cr.yaml
```

Проверяем, что Vault создан успешно (на это потребуется 1-4 минуты):

```bash
kubectl get pod -n vault-infra -l app.kubernetes.io/name=vault
```

Далее можно получить токен для доступа к созданному Vault вот такой командой:

```bash
kubectl get secrets vault-unseal-keys -o jsonpath={.data.vault-root} | base64 -d
```

Заходим браузером по адресу `http://vault.<Ваш Номер логина>.edu.slurm.io` (тут снова потребуется приватный режим, т.к. у нас нет TLS-сертификата). В качестве токена для входа используйте то, что получили в терминале шагом ранее. В веб-интерфейсе можно осмотреться, но дальнейшие действия по настройке Vault будут проходить в командной строке на `master-1`.

Для доступа к консоли Vault создадим под:

```bash
kubectl apply -f console.yaml # Предполагается, что console.yaml находится в текущей директории или указан полный путь
```

И вот такой командой туда будет можно зайти (выход - `Ctrl+D` или `exit`):

```bash
kubectl exec -it vault-console sh
```

Вот мы и добрались до настройки Vault.
Проверим статус:

```bash
vault status
```

Включаем тип авторизации `jwt`, нужный для интеграции с GitLab:

```bash
vault auth enable jwt
```

Создаём политики - для `staging`:

```bash
vault policy write myproject-staging - <<EOF
path "secret/data/myproject/staging/*" {
    capabilities = ["read"]
}
EOF
```

И для `production`:

```bash
vault policy write myproject-production - <<EOF
path "secret/data/myproject/production/*" {
    capabilities = ["read"]
}
EOF
```

Далее создадим роль для `staging`.
Тут нужно заполнить номер проекта, его можно взять в вашем форке в GitLab, сразу под названием. Выглядит это как `Project ID: xxxx` (у вас будут свои четыре цифры).

```bash
vault write auth/jwt/role/myproject-staging - <<EOF
{
  "role_type": "jwt",
  "policies": ["myproject-staging"],
  "token_explicit_max_ttl": 60,
  "user_claim": "user_email",
  "bound_claims": {
    "project_id": "<Ваш Номер проекта в Gitlab>",
    "ref_type": "branch"
  }
}
EOF
```

Тут ключевые штуки кроме `project_id` - это `ref` и `ref_type`, который указывают на шаблон имени и на тип объекта в проекте.
И подобным же образом создаём роль для `production`:

```bash
vault write auth/jwt/role/myproject-production - <<EOF
{
  "token_explicit_max_ttl": 60,
  "user_claim": "user_email",
  "bound_claims_type": "glob",
  "bound_claims": {
    "project_id": "<Ваш Номер проекта в Gitlab>",
    "ref": "master",
    "ref_protected": "true",
    "ref_type": "branch"
  }
}
EOF
```

Далее заполняем в Vault конфиг для `jwt`:

```bash
vault write auth/jwt/config \
    jwks_url="https://gitlab.slurm.io/-/jwks" \
    bound_issuer="gitlab.slurm.io"
```

Так как у нас в хранилище Vault "из коробки" не содержатся нужные секреты, мы их туда добавим вручную:

```bash
vault kv put secret/myproject/staging/db password='p@$$w0rd'
vault kv put secret/myproject/production/db password='real-p@$$w0rd'
```

Можно тут же проверить, что всё записалось правильно:

```bash
vault kv get -field=password secret/myproject/staging/db
# p@$$w0rd
vault kv get -field=password secret/myproject/production/db
# real-p@$$w0rd
```

На этом настройка Vault закончена, в GitLab вся настройка сводится к правильным формулировкам в описании конфигурации CI/CD.

## Интеграция Vault в .gitlab-ci.yml

Нам нужно внести изменения в файл `.gitlab-ci.yml`.
Новый этап:

```yaml
stages:
  - build
  - test
  - deploy
  - vault # Добавленный этап
```

И новый job, тут не забудьте заменить `VAULT_ADDR` на тот, который вы проверяли браузером:

```yaml
get_secrets:
  stage: vault
  image: vault:1.7.5
  script:
    - echo $CI_COMMIT_REF_NAME
    - echo $CI_COMMIT_REF_PROTECTED
    - export VAULT_ADDR=http://vault.<Ваш Номер логина>.edu.slurm.io
    - export VAULT_TOKEN="$(vault write -field=token auth/jwt/login role=myproject-production jwt=$CI_JOB_JWT)"
    - export STAGING_PASSWORD="$(vault kv get -field=password secret/myproject/staging/db)"
    - echo "Staging Password (masked): ${STAGING_PASSWORD}" # Добавлено для ясности, но вывод может быть скрыт
    - export PRODUCTION_PASSWORD="$(vault kv get -field=password secret/myproject/production/db)"
    - echo "Production Password (masked): ${PRODUCTION_PASSWORD}" # Добавлено для ясности, но вывод может быть скрыт
```

После этого примените изменения в репозиторий и посмотрите, какой будет вывод в логах вашего рабочего процесса CI/CD на этапе `vault`.
Если всё сделано правильно, в логе отобразится содержимое пароля для `production`.

Пароль для `staging` показан не будет и Vault выдаст ошибку, так как не были соблюдены условия, которые мы указали при создании роли (например, `ref_type: branch` для `staging` без конкретного `ref` и `ref_protected`).

