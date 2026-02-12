# Промоция образов между окружениями

## Рекомендуемый подход (Promotion)

```
Dev бранч:
  docker build -t myapp:dev-abc123 .
  docker tag myapp:dev-abc123 registry/app:dev-abc123
  
Тестирование в dev...
  ✓ Пройдены unit tests
  ✓ Пройдены integration tests
  
Stage бранч (merging dev → stage):
  # НЕ пересобираем! Промоутим проверенный образ
  docker pull registry/app:dev-abc123
  docker tag registry/app:dev-abc123 registry/app:stage-abc123
  docker push registry/app:stage-abc123
  
  # ИЛИ используем immutable digest
  docker buildx imagetools inspect \
    registry/app:dev-abc123 --format '{{ json .Manifest }}'
   
Production (merging stage → main):
  docker pull registry/app:stage-abc123
  docker tag registry/app:stage-abc123 registry/app:prod-abc123
  docker tag registry/app:stage-abc123 registry/app:1.2.3
  docker push registry/app:1.2.3
```

## Проверка идентичности образов

```bash
# Сравнение digests (SHA256)
docker inspect --format='{{index .RepoDigests 0}}' myapp:dev
docker inspect --format='{{index .RepoDigests 0}}' myapp:stage

# Если разные — разные артефакты!

# Просмотр всех слоев
docker history myapp:dev
docker history myapp:stage

# Сравнение с помощью dive
dive myapp:dev
dive myapp:stage

# Извлечение SBOM и сравнение
syft myapp:dev -o json > dev.sbom.json
syft myapp:stage -o json > stage.sbom.json
diff dev.sbom.json stage.sbom.json
```

## CI/CD стратегии

**Стратегия 1: Сборка в каждом бранче (простая)**
```yaml
build:
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG-$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG-$CI_COMMIT_SHORT_SHA
```

**Стратегия 2: Сборка один раз, промоция между окружениями**
```yaml
build:
  only:
    - dev
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

promote_to_stage:
  only:
    - stage
  script:
    - docker pull $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA $CI_REGISTRY_IMAGE:stage
    - docker push $CI_REGISTRY_IMAGE:stage
```

## Дополнительная информация

### Реверс-инжиниринг образов

**Внимание:** Это метод "последней надежды", если `Dockerfile` утерян.

- **[dduvnjak/dockerfile-from-image](https://github.com/dduvnjak/dockerfile-from-image)**
- **[laniksj/dfimage](https://github.com/LanikSJ/dfimage)**

### Подписание образов и безопасность

Для обеспечения целостности и аутентичности образов используется механизм цифровых подписей. Подробнее см. документацию по безопасности Docker.
