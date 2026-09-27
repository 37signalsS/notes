# SSH в CI/CD: безопасная автоматизация

## Определения

**Deploy Key** — SSH-ключ, предоставленный только одному репозиторию для доступа к зависимостям или серверам. В GitLab/GitHub имеет ограниченные права (read-only или read-write).

**Agent Forwarding** — проброс SSH-агента на раннер CI/CD для доступа к серверам без хранения приватных ключей. Рискованно: root на раннере может использовать сокет агента.

**OIDC (OpenID Connect) / Workload Identity** — современный стандарт «безсекретной» (secretless) аутентификации, позволяющий CI-системе подтверждать свою идентичность облачному провайдеру через временные JWT-токены.

**Vault SSH Secrets Engine** — компонент HashiCorp Vault для динамической генерации SSH-ключей и сертификатов. Устраняет необходимость хранения статических ключей на раннерах.

**SSH Certificate Authority (CA)** — централизованная инфраструктура для подписи SSH-сертификатов, исключая необходимость ручного управления `authorized_keys` на серверах.

## Базовые концепции

### Модели доступа по SSH в CI/CD

| Модель | Безопасность | Сложность | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Статический ключ в переменных CI** | Низкая | Низкая | Антипаттерн |
| **Deploy Key (read-only)** | Средняя | Низкая | Для зависимостей |
| **Agent Forwarding** | Средняя | Низкая | Только для dev |
| **Vault SSH (динамические ключи)** | Высокая | Средняя | Production |
| **OIDC + Workload Identity** | Очень высокая | Средняя | Золотой стандарт |

### Архитектура безопасного SSH-доступа

```
┌─────────────────────────────────────────────────────────┐
│                    CI/CD Pipeline                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  GitLab CI   │  │  GitHub      │  │  Jenkins      │  │
│  │  (OIDC)      │  │  Actions     │  │  (OIDC)       │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
└─────────┼────────────────┼──────────────────┼───────────┘
          │                │                  │
          v                v                  v
┌─────────────────────────────────────────────────────────┐
│              Vault SSH Secrets Engine                    │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  SSH CA Key  │  │  Dynamic     │  │  Certificate  │  │
│  │  (подпись)   │  │  Generation  │  │  Signing      │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────┐
│              Production Servers                          │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │
│  │ web-01 │ │ web-02 │ │ db-01  │ │ db-02  │  ...     │
│  └────────┘ └────────┘ └────────┘ └────────┘          │
└─────────────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: GitLab CI с Vault SSH (динамические сертификаты)

**Задача**: Получение временного SSH-сертификата из Vault для деплоя на production-серверы.

```yaml
deploy:
  image: hashicorp/vault:latest
  id_tokens:
    VAULT_OIDC_TOKEN:
      aud: https://vault.internal.corp
  script:
    # Получение временного SSH-сертификата
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=ci-deploy jwt=$VAULT_OIDC_TOKEN)
    - vault write -field=signed_key ssh-client-signer/sign/deploy-role \
        public_key=$CI_PROJECT_DIR/.ssh/id_ed25519.pub > .ssh/id_ed25519-cert.pub

    # Деплой через SSH с сертификатом
    - ssh -i .ssh/id_ed25519 \
        -o CertificateFile=.ssh/id_ed25519-cert.pub \
        deploy@prod-server "sudo systemctl restart app"

  after_script:
    # Очистка ключей
    - rm -rf .ssh/
```

### Сценарий 2: GitHub Actions с OIDC (без статических ключей)

**Задача**: Деплой на AWS EC2 через SSM без хранения ключей.

```yaml
deploy:
  runs-on: ubuntu-latest
  permissions:
    id-token: write
    contents: read
  steps:
    - name: Configure AWS credentials via OIDC
      uses: aws-actions/configure-aws-credentials@v4
      with:
        role-to-assume: arn:aws:iam::123456789:role/GitHubDeployRole
        aws-region: us-east-1

    - name: Deploy via SSM (без SSH)
      run: |
        aws ssm send-command \
          --document-name "AWS-RunShellScript" \
          --targets "Key=instanceids,Values=i-0123456789abcdef0" \
          --parameters 'commands=["sudo systemctl restart app"]'
```

### Сценарий 3: Jenkins с Vault AppRole

**Задача**: Аутентификация Jenkins в Vault через AppRole для получения SSH-ключей.

```groovy
// Jenkinsfile
pipeline {
    agent any
    environment {
        VAULT_ROLE_ID = credentials('vault-role-id')
        VAULT_SECRET_ID = credentials('vault-secret-id')
    }
    stages {
        stage('Get SSH Key from Vault') {
            steps {
                script {
                    // Аутентификация через AppRole
                    def vaultToken = sh(
                        script: """
                            vault write -field=token auth/approle/login \
                                role_id=${VAULT_ROLE_ID} \
                                secret_id=${VAULT_SECRET_ID}
                        """,
                        returnStdout: true
                    ).trim()

                    // Получение SSH-ключа
                    def sshKey = sh(
                        script: """
                            vault kv get -field=private_key kv/deploy/ssh-key
                        """,
                        returnStdout: true
                    ).trim()

                    // Запись ключа во временный файл
                    writeFile file: '.ssh/id_ed25519', text: sshKey
                    sh 'chmod 600 .ssh/id_ed25519'
                }
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    ssh -i .ssh/id_ed25519 \
                        -o StrictHostKeyChecking=no \
                        deploy@prod-server "sudo systemctl restart app"
                '''
            }
        }
    }

    post {
        always {
            // Очистка ключей
            sh 'rm -rf .ssh/'
        }
    }
}
```

### Сценарий 4: Деплой через bastion с SSH-туннелем

**Задача**: Доступ к production-серверам через bastion из CI/CD.

```yaml
# GitLab CI example
deploy:
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
  script:
    - ssh -o StrictHostKeyChecking=no \
        -o ProxyJump=admin@bastion.example.com \
        deploy@prod-server "sudo systemctl restart app"
  variables:
    SSH_PRIVATE_KEY: $PROD_SSH_KEY  # Stored in GitLab CI/CD variables (masked)
```

### Сценарий 5: Безопасная настройка Deploy Key

**Задача**: Настройка read-only SSH-ключа для доступа к приватным зависимостям.

```bash
# 1. Генерация ключа专门 для CI/CD
ssh-keygen -t ed25519 -C "ci-deploy@company.com" -f ci_deploy_key

# 2. Добавление в GitLab/GitHub как Deploy Key (read-only)
# GitLab: Settings → Repository → Deploy Keys → Add key
# GitHub: Settings → Deploy keys → Add deploy key

# 3. Настройка SSH config
cat >> ~/.ssh/config << EOF
Host gitlab.com
    IdentityFile ~/.ssh/ci_deploy_key
    IdentitiesOnly yes
EOF

# 4. Проверка доступа
ssh -T git@gitlab.com
```

## Дополнительная информация

### Частые ошибки

| Ошибка | Решение |
| :--- | :--- |
| Секреты в переменных CI/CD | Используйте Vault с OIDC |
| Статические SSH-ключи без ротации | Динамические сертификаты через Vault SSH |
| Agent Forwarding на production | Используйте ProxyJump или Vault |
| Нет audit trail | Включите Vault Audit Devices |

### См. также

- [Управление секретами в CI/CD](../../CI-CD/DevSecOps/secrets_management.md) — секреты в пайплайнах
- [Атаки на CI/CD](../../CI-CD/DevSecOps/cicd_attacks.md) — векторы атак
- [Усиление безопасности CI/CD](../../CI-CD/Core_Concepts/ci_cd_security_hardening.md) — hardening
- [SSH-аутентификация по сертификатам](./server/ssh_certificate_authentication.md) — SSH CA
- [Управление SSH-ключами в масштабе](./server/ssh_key_management_at_scale.md) — ключи в инфраструктуре
- [Инструменты сетевого мониторинга](../Tools/network_monitoring_tools.md) — tcpdump, tshark, ss для анализа SSH-трафика
