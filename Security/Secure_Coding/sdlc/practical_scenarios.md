# Практические сценарии Secure SDLC

## Сценарий 1: Внедрение SAST в CI/CD

```yaml
# GitHub Actions workflow
name: Security Scan

on: [push, pull_request]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Run Semgrep
      uses: returntocorp/semgrep-action@v1
      with:
        config: >-
          p/security-audit
          p/owasp-top-ten
          p/cwe-top-25
    
    - name: Dependency Check
      uses: snyk/actions/node@master
      env:
        SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}
    
    - name: Upload results
      uses: github/codeql-action/upload-sarif@v2
      if: always()
      with:
        sarif_file: semgrep-results.sarif
```

## Сценарий 2: Threat Modeling с STRIDE

```
Пример: Веб-приложение для онлайн-банкинга

Data Flow Diagram:
┌────────┐      ┌──────────┐      ┌──────────┐      ┌────────┐
│ User   │──────►│   WAF    │──────►│ Web App  │──────►│Database│
└────────┘      └──────────┘      └──────────┘      └────────┘
                       │                 │
                       │            ┌────▼────┐
                       │            │  API    │
                       │            └────┬────┘
                       │                 │
                  ┌────▼────┐      ┌────▼────┐
                  │  Logs   │      │ Payment │
                  └─────────┘      └─────────┘

STRIDE Analysis:
1. User → WAF: Spoofing (fake user), Tampering (modify request)
2. WAF → Web App: Denial of Service (bypass WAF)
3. Web App → Database: Information Disclosure (SQL injection)
4. Web App → Payment: Repudiation (no audit logs)
5. Internal → Logs: Elevation of Privilege (admin access)
```

## Сценарий 3: Security Champions Program

```
Структура:
├── Security Team (централизованная функция)
│   ├── Security Architecture
│   ├── AppSec Engineers
│   └── Security Operations
│
└── Security Champions (в каждой команде разработки)
    ├── Dev Team A: Champion John
    ├── Dev Team B: Champion Jane
    └── Dev Team C: Champion Bob

Обязанности Security Champion:
- 20% времени на security
- Review security issues
- Обучение команды
- Связь с Security Team
- Участие в threat modeling
```

## Дополнительная информация

- [OWASP SAMM](https://owasp.org/www-project-samm/)
- [BSIMM](https://www.bsimm.com/)
- [Microsoft SDL](https://www.microsoft.com/en-us/securityengineering/sdl)
- [NIST SSDF](https://csrc.nist.gov/projects/ssdf)
- [OWASP DevSecOps Guideline](https://owasp.org/www-project-devsecops-guideline/)
