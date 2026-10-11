# Podman в CI/CD пайплайнах

## GitLab CI

### Executor podman
```yaml
# .gitlab-ci.yml
variables:
  STORAGE_DRIVER: "overlay"

job_build:
  image: localhost/podman-build:latest
  tags:
    - podman
  script:
    - podman build -t myapp:$CI_COMMIT_SHA .
    - podman push myapp:$CI_COMMIT_SHA registry.example.com/myapp:$CI_COMMIT_SHA
```

### DinD-стиль (rootless)
```yaml
variables:
  DOCKER_HOST: "unix:///run/user/1000/podman/podman.sock"

before_script:
  - podman info
```

### Кэширование образов
```yaml
cache:
  key: podman-images
  paths:
    - /var/lib/containers/storage/overlay

build:
  script:
    - podman pull registry.example.com/base:latest || true
    - podman build --layers -t myapp .
```

### Multi-platform сборка
```yaml
build_multiarch:
  script:
    - podman manifest create myapp:latest
    - podman build --arch amd64 -t myapp:amd64 .
    - podman build --arch arm64 -t myapp:arm64 .
    - podman manifest add myapp:latest myapp:amd64
    - podman manifest add myapp:latest myapp:arm64
    - podman manifest push myapp:latest
```

---

## GitHub Actions

### Self-hosted runner с Podman
```yaml
# .github/workflows/build.yml
name: Build with Podman

on: [push, pull_request]

jobs:
  build:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      
      - name: Build image
        run: podman build -t myapp:${{ github.sha }} .
      
      - name: Run tests
        run: podman run --rm myapp:${{ github.sha }} npm test
      
      - name: Push to registry
        run: |
          podman login -u ${{ secrets.REGISTRY_USER }} -p ${{ secrets.REGISTRY_PASS }}
          podman push myapp:${{ github.sha }} ghcr.io/${{ github.repository }}:${{ github.sha }}
```

### Matrix сборка
```yaml
strategy:
  matrix:
    arch: [amd64, arm64]

steps:
  - name: Build for ${{ matrix.arch }}
    run: podman build --arch ${{ matrix.arch }} -t myapp:${{ matrix.arch }} .
```

### Container scanning (Trivy)
```yaml
scan:
  runs-on: self-hosted
  steps:
    - name: Build
      run: podman build -t myapp:scan .
    
    - name: Trivy scan
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: myapp:scan
        format: table
        exit-code: 1
        severity: CRITICAL,HIGH
```

---

## Jenkins

### Jenkinsfile с Podman
```groovy
pipeline {
    agent { label 'podman' }
    
    environment {
        REGISTRY = 'registry.example.com'
        IMAGE = "${REGISTRY}/myapp"
    }
    
    stages {
        stage('Build') {
            steps {
                sh 'podman build -t ${IMAGE}:${BUILD_NUMBER} .'
            }
        }
        
        stage('Test') {
            steps {
                sh 'podman run --rm ${IMAGE}:${BUILD_NUMBER} npm test'
            }
        }
        
        stage('Push') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'registry-creds',
                    usernameVariable: 'USER',
                    passwordVariable: 'PASS'
                )]) {
                    sh 'podman login -u $USER -p $PASS ${REGISTRY}'
                    sh 'podman push ${IMAGE}:${BUILD_NUMBER}'
                }
            }
        }
    }
}
```

### Podman в Jenkins Pipeline
```groovy
// Установка Podman на Jenkins агенте
stage('Setup') {
    steps {
        sh '''
            sudo apt-get update
            sudo apt-get install -y podman
            podman info
        '''
    }
}
```

---

## Кэширование образов в CI

### Локальный кэш (overlay)
```yaml
# GitLab CI
build:
  cache:
    key: podman-cache
    paths:
      - /var/lib/containers/storage/
  script:
    - podman build --layers -t myapp .
```

### Registry как кэш
```yaml
build:
  script:
    - podman pull ${REGISTRY}/myapp:cache || true
    - podman build --cache-from ${REGISTRY}/myapp:cache -t myapp .
    - podman push myapp ${REGISTRY}/myapp:cache
```

### BuildKit кэш
```yaml
build:
  variables:
    BUILDAH_ISOLATION: "chroot"
  script:
    - podman build --layers --cache-from ${REGISTRY}/myapp:cache -t myapp .
```

---

## Multi-stage builds в CI

### Параллельная сборка этапов
```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Runtime stage
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
CMD ["node", "dist/index.js"]
```

### CI-скрипт для multi-stage
```bash
#!/bin/bash
set -e

# Сборка всех этапов
podman build --target builder -t myapp:build .

# Извлечение артефактов
CONTAINER_ID=$(podman create myapp:build)
podman cp $CONTAINER_ID:/app/dist ./dist
podman rm $CONTAINER_ID

# Финальный образ
podman build -t myapp:latest .
```

---

## Тестирование в контейнерах

### Unit-тесты
```yaml
test_unit:
  script:
    - podman run --rm -v $(pwd):/app -w /app node:20-alpine npm test
```

### Интеграционные тесты
```yaml
test_integration:
  services:
    - postgres:15
    - redis:7
  script:
    - |
      podman run -d --name test-postgres \
        -e POSTGRES_PASSWORD=test \
        -p 5432:5432 postgres:15
    - |
      podman run -d --name test-redis \
        -p 6379:6379 redis:7
    - sleep 5
    - podman run --rm \
        --network host \
        -e DATABASE_URL=postgresql://postgres:test@localhost:5432/test \
        myapp:test npm run test:integration
```

### E2E тесты
```yaml
test_e2e:
  script:
    - podman-compose -f docker-compose.test.yml up -d
    - sleep 10
    - podman run --rm --network host myapp:test npm run test:e2e
    - podman-compose -f docker-compose.test.yml down
```

---

## Безопасность в CI

### Rootless сборка
```yaml
variables:
  STORAGE_DRIVER: "fuse-overlayfs"
  TMPDIR: "/tmp/podman-tmp"

build:
  before_script:
    - mkdir -p $TMPDIR
  script:
    - podman build --storage-driver=fuse-overlayfs -t myapp .
```

### Сканирование секретов
```yaml
scan_secrets:
  script:
    - podman run --rm -v $(pwd):/repo trufflesecurity/trufflehog:latest filesystem /repo
```

### Проверка лицензий
```yaml
license_check:
  script:
    - podman run --rm -v $(pwd):/app licensedetect --dir /app
```

---

## Артефакты CI

### Сохранение образов
```yaml
# GitLab CI
build:
  artifacts:
    paths:
      - ./image-*.tar
  script:
    - podman build -t myapp .
    - podman save -o image-${CI_COMMIT_SHA}.tar myapp
```

### Загрузка артефактов
```yaml
deploy:
  dependencies:
    - build
  script:
    - podman load -i image-*.tar
    - podman push myapp:latest ${REGISTRY}/myapp:latest
```

---

## Troubleshooting в CI

### Диагностика
```bash
# Логи сборки
podman build --log-level=debug -t myapp .

# Проверка хранилища
podman system info | grep -A 10 "store"

# Очистка перед сборкой
podman system prune -af

# Проверка сетей
podman network ls
podman network inspect podman
```

### Частые ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `ERRO[0001] error creating overlay mount` | Проблемы с overlay | `--storage-driver=fuse-overlayfs` |
| `Error: no space left on device` | Мало места | `podman system prune -af` |
| `Error: unable to find user` | Несуществующий USER | Убрать `USER` из Dockerfile или создать |
| `Error: error running hook` | Проблемы с OCI | `--security-opt seccomp=unconfined` |

---

## Пример: Полный пайплайн

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - scan
  - push
  - deploy

variables:
  REGISTRY: "registry.example.com"
  IMAGE: "${REGISTRY}/myapp"

build:
  stage: build
  script:
    - podman build --layers -t ${IMAGE}:${CI_COMMIT_SHA} .
    - podman save -o image.tar ${IMAGE}:${CI_COMMIT_SHA}
  artifacts:
    paths:
      - image.tar

test:
  stage: test
  dependencies:
    - build
  script:
    - podman load -i image.tar
    - podman run --rm ${IMAGE}:${CI_COMMIT_SHA} npm test

scan:
  stage: scan
  dependencies:
    - build
  script:
    - podman load -i image.tar
    - podman run --rm aquasec/trivy image ${IMAGE}:${CI_COMMIT_SHA}

push:
  stage: push
  dependencies:
    - scan
  script:
    - podman load -i image.tar
    - podman tag ${IMAGE}:${CI_COMMIT_SHA} ${IMAGE}:latest
    - podman push ${IMAGE}:${CI_COMMIT_SHA}
    - podman push ${IMAGE}:latest
  only:
    - main

deploy:
  stage: deploy
  script:
    - podman run --rm ${IMAGE}:latest deploy.sh
  only:
    - main
```

# force reindex test
