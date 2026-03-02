# Дополнительные параметры `include`

## `include:inputs`

Передача входных параметров в подключаемый файл (для компонентов и шаблонов с `spec:inputs`).

```yaml
include:
  - local: '.gitlab-ci/build.yml'
    inputs:
      environment: production
      enable_cache: true
```

## `include:rules`

Условное включение файлов.

```yaml
include:
  - local: '.gitlab-ci/deploy.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "main"'
```

Файл будет включён только если условие истинно.

## `include:integrity`

Проверка целостности удалённого файла через SHA256 (GitLab 17.9+).

```yaml
include:
  - remote: 'https://example.com/.gitlab-ci.yml'
    integrity: 'sha256-<hash>'
```
