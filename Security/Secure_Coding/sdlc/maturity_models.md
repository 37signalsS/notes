# Maturity Models для Secure SDLC

## BSIMM (Building Security In Maturity Model)

- Оценка зрелости безопасности
- 4 уровня: начальный, управляемый, определенный, оптимизирующий

## OWASP SAMM (Software Assurance Maturity Model)

- Governance
- Design
- Implementation
- Verification
- Operations

## Метрики Secure SDLC

| Метрика | Цель | Как измерять |
|---------|------|--------------|
| **Defect density** | < 0.1 defects/LOC | Баги / строки кода |
| **Time to fix** | Критические: < 24h | MTTR для security багов |
| **False positive rate** | < 20% | FP / (TP + FP) |
| **Security test coverage** | > 80% | Security tests / Total tests |
| **Vulnerability escape rate** | 0 critical in prod | Баги найденные в production |
| **Mean time to patch** | < 7 days для critical | Время от disclosure до patch |
