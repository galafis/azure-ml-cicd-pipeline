# Contributing / Contribuindo

## English

### How to Contribute

Thank you for your interest in contributing to this project! Follow the steps below to get started.

#### Prerequisites

- Python 3.11+
- Azure CLI with Bicep extension
- Docker (optional, for containerized workflows)
- An Azure subscription (for integration testing)

#### Setup

1. **Fork the repository** and clone it locally:
   ```bash
   git clone https://github.com/<your-username>/azure-ml-cicd-pipeline.git
   cd azure-ml-cicd-pipeline
   ```

2. **Create a virtual environment** and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   make install-dev
   ```

3. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

#### Development Workflow

1. **Write code** following the existing patterns and conventions.
2. **Add tests** for new functionality in `tests/unit/` or `tests/integration/`.
3. **Run quality checks**:
   ```bash
   make quality   # Lint + format check + type check
   make test      # Run all tests
   make coverage  # Tests with coverage report
   ```
4. **Commit** with clear, descriptive messages.
5. **Open a Pull Request** against the `main` branch.

#### Code Standards

- Follow PEP 8 style guidelines (enforced by Ruff).
- Add type hints to all function signatures.
- Write docstrings for all public classes and methods.
- Maintain test coverage above 80%.

#### Reporting Issues

- Use GitHub Issues to report bugs or request features.
- Provide clear reproduction steps for bugs.
- Include environment details (Python version, OS, Azure SDK version).

---

## Portugues

### Como Contribuir

Obrigado pelo interesse em contribuir com este projeto! Siga os passos abaixo para comecar.

#### Pre-requisitos

- Python 3.11+
- Azure CLI com extensao Bicep
- Docker (opcional, para workflows containerizados)
- Uma assinatura Azure (para testes de integracao)

#### Configuracao

1. **Faca um fork do repositorio** e clone localmente:
   ```bash
   git clone https://github.com/<seu-usuario>/azure-ml-cicd-pipeline.git
   cd azure-ml-cicd-pipeline
   ```

2. **Crie um ambiente virtual** e instale as dependencias:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # No Windows: .venv\Scripts\activate
   make install-dev
   ```

3. **Crie uma branch para sua feature**:
   ```bash
   git checkout -b feature/nome-da-feature
   ```

#### Fluxo de Desenvolvimento

1. **Escreva codigo** seguindo os padroes e convencoes existentes.
2. **Adicione testes** para novas funcionalidades em `tests/unit/` ou `tests/integration/`.
3. **Execute verificacoes de qualidade**:
   ```bash
   make quality   # Lint + verificacao de formato + type check
   make test      # Executar todos os testes
   make coverage  # Testes com relatorio de cobertura
   ```
4. **Faca commit** com mensagens claras e descritivas.
5. **Abra um Pull Request** para a branch `main`.

#### Padroes de Codigo

- Siga as diretrizes de estilo PEP 8 (aplicado pelo Ruff).
- Adicione type hints em todas as assinaturas de funcoes.
- Escreva docstrings para todas as classes e metodos publicos.
- Mantenha a cobertura de testes acima de 80%.

#### Reportando Problemas

- Use GitHub Issues para reportar bugs ou solicitar funcionalidades.
- Forneca passos claros de reproducao para bugs.
- Inclua detalhes do ambiente (versao do Python, SO, versao do Azure SDK).

---

**Maintainer / Mantenedor:** Gabriel Demetrios Lafis ([@galafis](https://github.com/galafis))
