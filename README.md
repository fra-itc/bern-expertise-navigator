# Hack Apertus Liebefeld — Research & Expertise Navigator, TODO(team): team name

Our submission to [Hack Apertus](https://hackapertus.ch/) (Liebefeld), challenge 1: Bern Economic Development
Agency — Research & Expertise Navigator.

One search box over the public websites of the University of Bern, the ARTORG Center and Diabetes Center
Berne. It understands natural-language and lay-term questions ("glucose sensors" also finds "continuous glucose
monitoring") and returns people, units, expertise, projects and infrastructure. Every result is structured,
explained and linked to the public page and verbatim snippet that support it, and the system says so when no
source supports an answer. A staff workspace for the canton's business-development team turns a company request
into matched partners and an executive brief. It includes a broad search that proposes companies verified on their own
websites, and a dashboard of Apertus cost per request and search recall. Built on Apertus v1.5. **Code and run instructions:
[`src/README.md`](src/README.md); write-up: [technical_report.md](technical_report.md).**

Two deployment modes, described honestly in [technical_report.md §2](technical_report.md#2-architecture):

- **Self-hosted / air-gapped:** `src/docker-compose.yml` with the `gpu` profile (vLLM serving Apertus 8B locally).
  After the crawl, no network is needed at runtime in rules mode or with the local vLLM (the only exception is
  fetching a company's website when a request includes its link).
- **Team server (the live demo):** a Hetzner server in Nuremberg, Germany, calling Apertus 70B through a remote
  OpenAI-compatible gateway (`gateway.keera.ch`; location declared by the provider, not verified by us). In this
  mode search queries and company requests go over the network to the LLM gateway, and company websites are
  fetched at runtime.

Submissions must use the v1.5 Apertus model family.
The submission must comply with the [HackApertus T&C](https://hackapertus.ch/terms-and-conditions).

## 🎯 The Challenge

Bern Economic Development Agency: **Research & Expertise Navigator** — TODO(team): link to the Notion challenge page

## 🔧 Resources & Tools

Check our resources & tools page for detailed information:
[https://hackapertus.notion.site/liebefeld-resources-tools](https://hackapertus.notion.site/liebefeld-resources-tools)

| Models           | URL                                      |
|------------------|------------------------------------------|
| Apertus v1.5 8B  | [huggingface.co/swiss-ai/Apertus-v1.5-8B](https://huggingface.co/swiss-ai/Apertus-v1.5-8B)  |
| Apertus v1.5 70B | [huggingface.co/swiss-ai/Apertus-v1.5-70B](https://huggingface.co/swiss-ai/Apertus-v1.5-70B) |

## The structure

Keep the files and directories as shown below — don't rename or move them.

| Path | What it is |
| --- | --- |
| `README.md` | The challenge description and submission requirements |
| `technical_report.md` | The deeper write-up: architecture, evaluation, limitations |
| `LICENSE` | Apache-2.0 (source code); documentation and the report are CC-BY-4.0, see [License](#license) |
| `src/` | Your code |

## Environment

- Include instructions for running the project in your technical report.
- Use the following environment variables:
```
LLM_NAME — name and version of the model
LLM_BASE_URL — endpoint base URL
LLM_API_KEY — your API key
```

## 📦 Submission Requirements & Deliverables

The submission must:
1. follow the template repo and include all prerequisite files and definitions
2. run end-to-end when judges try to run it

### Git repo (URL)
- Create your repo from this template (**Use this template**).
- Keep the layout as it is: don't rename or move its files.
- Set the repo to PUBLIC (Settings --> Collaborators --> Manage Visibility)
- Submit the URL of YOUR Git repo.

### Technical Report (pdf)
- Update [technical_report.md](technical_report.md) in this repository with all the details for your submission.
- Upload a pdf of your technical report to the root of the repo, named as `TeamName_Report.pdf`.
- Format: pdf, max. 6 pages w/o references
- Submit the pdf of the technical report.
- Status: TODO(team): `TeamName_Report.pdf` (with the real team name) is not in the repository yet.

### Demo video (URL)
- Max. 2 min demo video of your prototype
- Add the link to the **Demo** field at the top of [technical_report.md](technical_report.md)
- Submit the URL of the video.
- Status: TODO(team): demo video not recorded/linked yet.

## ⚖️ Judging Criteria

Each challenge has its own criteria, listed in its challenge description.

The main jury scores every submission on 6 dimensions (relevant for Top 6 teams):
1. **Purposeful use of AI**
2. **Technical rigour**
3. **Value, cost & scalability**
4. **Sovereign deployability**
5. **Implementation feasibility**
6. **Pitch & presentation**

Each dimension is scored from 0 to 5.

## License

All Hack Apertus projects are open-sourced under the [HackApertus T&C](https://hackapertus.ch/terms-and-conditions),
§6 "What you build is open source":

- **Source code:** Apache License 2.0 ([`LICENSE`](LICENSE)).
- **Documentation and non-code materials** (this README, [technical_report.md](technical_report.md), the report
  PDF): Creative Commons Attribution 4.0 (CC-BY-4.0).
- **Submitted datasets**, if any: CDLA-Permissive-2.0. The crawled pages in `data/` are not in the repository;
  their copyright stays with the institutions.

## Support

### FAQ
💡 https://hackapertus.ch/faq

### Contact

💬 In case you have questions, join the conversation on Discord. Alternatively, send an email to “hello@hackapertus.ch”.
