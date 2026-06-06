# Aspectos Legais e Conformidade (LGPD & LAI)

Este documento descreve a fundamentação jurídica, os riscos identificados e as medidas de mitigação adotadas pelo projeto **Bolsas Quissamã** para garantir a conformidade com as leis brasileiras de privacidade e acesso à informação.

---

## 1. Fundamentação Jurídica (Por que o site é legal?)

O agrupamento e a exibição de dados de bolsas de estudo financiadas por recursos públicos são protegidos pelas seguintes legislações:

### A. Lei de Acesso à Informação (LAI - Lei nº 12.527/2011)
A LAI estabelece a **transparência ativa** como regra geral para a administração pública. Os gastos municipais, incluindo o pagamento de benefícios individuais a cidadãos como bolsas de estudo (recursos públicos), são informações de interesse público e devem ser disponibilizados para livre consulta. A organização desse ecossistema para facilitar o controle social é um exercício de cidadania protegido constitucionalmente.

### B. Lei Geral de Proteção de Dados (LGPD - Lei nº 13.709/2018)
A LGPD regulamenta o tratamento de dados pessoais de cidadãos, porém traz regras específicas para dados públicos:
*   **Art. 7º, § 3º:** O tratamento de dados pessoais cujo acesso é público deve considerar a finalidade, a boa-fé e o interesse público que justificaram sua disponibilização.
*   **Art. 7º, § 4º:** É dispensada a exigência do consentimento do titular para o tratamento de dados tornado manifestamente públicos pelo controlador (neste caso, a Prefeitura de Quissamã no seu Portal da Transparência).
*   **Finalidade Preservada:** A publicação das despesas no portal oficial da prefeitura tem a finalidade explícita de permitir a fiscalização e a transparência pública. O projeto **Bolsas Quissamã** cumpre exatamente essa mesma finalidade, estruturando a visualização para facilitar a leitura social dos dados.

---

## 2. Riscos Jurídicos e de Reputação

Embora amparado pela lei, o projeto está sujeito a atritos do mundo real com administrações municipais ou indivíduos. Os principais riscos identificados são:

### A. Pressão Política e Notificações Extrajudiciais (SLAPP)
*   **O Risco:** A prefeitura ou sua procuradoria pode emitir notificações extrajudiciais ou ameaçar com processos de difamação ou "quebra de privacidade" na tentativa de intimidar o desenvolvedor e forçar a remoção do site (prática conhecida como litígio estratégico contra a participação pública).
*   **Mitigação:** Manter a calma, responder com base na LAI/LGPD e reafirmar a natureza pública e oficial dos dados de origem.

### B. Erros na Engenharia de Dados (Crítico)
*   **O Risco:** Caso haja alguma falha de lógica no script de parsing ou no mapeamento canônico (*fuzzy matching* de nomes), o site pode exibir valores incorretos, parcelas atrasadas que já foram pagas, ou atribuir despesas a alunos homônimos incorretos. Isso pode expor o desenvolvedor a processos de **danos morais** por difamação ou calúnia por parte do cidadão prejudicado.
*   **Mitigação:** 
    *   Testes exaustivos na lógica do `csv_loader.py` e `coletar_bolsas.py`.
    *   Não manipular os valores manualmente.
    *   Garantir integridade total em relação ao CSV bruto original.

### C. Solicitação de Ocultação ("Direito ao Esquecimento")
*   **O Risco:** Alunos bolsistas que se sintam expostos ou constrangidos podem requerer judicialmente ou de forma amigável a exclusão de seus nomes do agregador de buscas do site.
*   **Mitigação:** Disponibilizar um e-mail de contato amigável para avaliar essas solicitações caso a caso.

### D. Denúncias de Phishing / Clonagem de Identidade
*   **O Risco:** A prefeitura pode denunciar o domínio ao `Registro.br` ou ao provedor de infraestrutura (`Render`), alegando que o site finge ser um portal governamental para enganar cidadãos.
*   **Mitigação:** Tornar evidente que o projeto é independente (veja a seção 3).

---

## 3. Diretrizes de Blindagem do Portal (Boas Práticas)

Para manter o projeto protegido e afastar qualquer questionamento legal, as seguintes regras de UX/UI e infraestrutura devem ser rigorosamente seguidas:

### 1. Isenção de Responsabilidade (Disclaimer Claro)
O rodapé e a página inicial devem conter de forma explícita o aviso de não-oficialidade:
> *"Este é um portal independente, de caráter estritamente informativo e cidadão. Não possuímos qualquer vínculo com a Prefeitura Municipal de Quissamã ou com o programa oficial de bolsas. Os dados exibidos são replicados e consolidados do Portal da Transparência de Quissamã (https://webapp1-quissama.cidade360.cloud/pronimtb/index.asp?acao=3&item=11). Não nos responsabilizamos por omissões ou erros nos dados originais publicados pelo município."*

### 2. Contato para Correções e Dúvidas
Um e-mail de contato (ex: `contato@bolsasquissama.com.br` ou similar) deve estar visível no rodapé para permitir que usuários reportem erros ou façam requisições amigáveis antes de buscar vias judiciais.

### 3. Links Diretos de Auditoria
Sempre que exibir a página de detalhes de um bolsista, o site deve conter um link de redirecionamento para o Portal da Transparência original, provando que a fonte do dado é pública e permitindo a auditoria em tempo real pelo usuário.

### 4. Não Armazenamento de CPFs (LGPD Estrita)
Para fins de conformidade máxima com a LGPD e segurança de banco de dados, o site não deve coletar, armazenar ou expor CPFs completos dos estudantes em arquivos públicos legíveis (como JSONs servidos no frontend). O identificador público padrão deve ser estritamente o **Nome Canônico** do bolsista conforme registrado nas despesas públicas da prefeitura.
