<a name="readme-top"></a>

<div align="center">
  <a href="https://github.com/RonsGit/DL4CV">
    <img src="Pictures/transperent_logo.png" alt="Logo" width="800" height="266">
  </a>

  <h3 align="center">Deep Learning for Computer Vision</h3>

  <p align="center">
    An open-source, comprehensive guide and companion reference for the world of Computer Vision.
    <br />
    <br />
    <a href="https://fuzzy-succotash-wrp8yol.pages.github.io/"><strong>📖 READ THE BOOK HERE »</strong></a>
    <br />
    <br />
    <em>The website above is the primary way to read the content. This repository is for tracking issues, suggesting changes, and technical contributions.</em>
    <br />
    <br />
    <a href="https://github.com/RonsGit/DL4CV/issues">Report Bug</a>
    ·
    <a href="https://github.com/RonsGit/DL4CV/issues">Request Feature</a>
    ·
    <a href="https://github.com/RonsGit/DL4CV/issues">Send Feedback</a>
  </p>
</div>

<div align="center">

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]

</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#disclaimer">Disclaimer</a></li>
      </ul>
    </li>
    <li><a href="#getting-started">Getting Started</a></li>
    <li>
        <a href="#development-and-building">Development & Building</a>
        <ul>
            <li><a href="#editing-content">Editing Content</a></li>
            <li><a href="#building-locally">Building Locally</a></li>
        </ul>
    </li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#releases-and-versioning">Releases & Versioning</a></li>
    <li><a href="#contact-and-feedback">Contact & Feedback</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

---

## About The Project

**Deep Learning for Computer Vision** is a community-driven open-source initiative designed to create an accessible, structured, and **comprehensive resource** for students, researchers, and practitioners entering the **Computer Vision field**.

The field of Deep Learning evolves at a breakneck pace. To ensure this resource remains relevant and accurate, it is built as an **open-source project**. By leveraging the collective knowledge of the CV community, we can ensure the content stays up-to-date with new advancements and community feedback.

The core goal of this book is to bridge the gap between abstract lecture concepts, seminal research papers, and practical implementation. It organizes knowledge in a coherent, navigable format, creating a resource that you can learn from effectively and revisit as a long-term reference.

This project originated as a structured companion to the University of Michigan’s EECS498 curriculum by **Ron Korine**, but has since evolved into a standalone, community-supported resource.

### Disclaimer
> **Note:** I (Ron Korine) am **not** part of the official course staff for the university courses mentioned in this text (such as EECS498).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Getting Started

> **🛑 For Readers:** You do **not** need to install anything to read the book! Simply visit the [**Live Website**](https://fuzzy-succotash-wrp8yol.pages.github.io/).
>
> **For Contributors:** Follow the steps below **only** if you intend to run the build pipeline locally to contribute code, fix typos, or add new chapters.

### Prerequisites
* **LaTeX Distribution**: Ensure you have a full TeX distribution installed (TeX Live recommended).
* **Python**: Version 3.9+ is required.
* **Editor**: We recommend **TeXStudio** for editing the `.tex` files to ensure they render correctly before building the full website.

### Installation

1.  **Clone the repository**
    ```sh
    git clone https://github.com/RonsGit/DL4CV.git
    cd DL4CV
    ```
2.  **Install Python dependencies**
    (See `build.yml` for the most up-to-date requirements)
    ```sh
    pip install pymupdf pypdf beautifulsoup4 pygments regex autopep8
    ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Development and Building

This project is Open Source. Readers are highly encouraged to suggest changes, create pull requests to update content, add new sections, or fix mistakes.

### Architecture & Security Note
This project relies on a custom **Static Site Generation (SSG)** pipeline.
* **No Server:** The build process does **not** launch a local web server, open network ports, or run background daemons.
* **Static Output:** The Python scripts simply read your source `.tex` files and write static `.html` and `.pdf` files to the `html_output/` directory.
* **Safe Execution:** The build is a strictly local file-transformation process. You can inspect the output files directly in your browser without needing a running backend.

### Editing Content
The core content of the book is located in the `Chapters/` directory.
1.  Open the relevant chapter `.tex` file in **TeXStudio**.
2.  Make your edits or additions.
3.  Compile locally within TeXStudio to verify that the LaTeX renders correctly (equations, figures, references).

### Building Locally
To generate the full website and PDFs, run the build pipeline below. This will populate the `html_output/` folder with the static site.

> **Platform Note:** The full build pipeline (particularly `pagefind` for search and `ghostscript` for compression) is optimized for **Linux** environments (or WSL on Windows). While the Python scripts are cross-platform, some external tools may require specific configurations on Windows.

**The Build Pipeline:**
Our CI/CD (controlled by `build.yml`) orchestrates the following sequence to produce the final artifacts. To replicate the full build locally:

1.  **Build Manager** (Compiles Content):
    ```sh
    python build_manager.py
    ```
2.  **Split PDF** (Extracts Chapters):
    ```sh
    python scripts/split_pdf.py --main-pdf html_output/downloads/main.pdf --toc html_output/main.toc --out-dir html_output/downloads
    ```
3.  **Build Bibliography** (Generates Standalone Bib):
    ```sh
    python scripts/build_bib_pdf.py --out html_output/downloads/Bibliography.pdf
    ```
4.  **Post-Processor** (Generates Website):
    ```sh
    python scripts/run_post_processor.py
    ```

Once finished, simply open `html_output/index.html` in your web browser to view the changes.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Contributing

Contributions are what make the open-source community such an amazing place to learn, inspire, and create. This project lives by the community's involvement.

**We actively encourage you to:**
* **Suggest improvements**: Clarify explanations, fix typos, or improve figures.
* **Add new parts**: Propose new chapters or sections on emerging topics.
* **Raise inquiries**: Ask questions or discuss potential changes via Issues.

Any contributions you make are **greatly appreciated**.

**Please Note:**
* Merge requests are **not guaranteed** to be accepted.
* Acceptance depends heavily on the **quality** of the writing, technical accuracy, and adherence to the project's style.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".

### Proposing New Features
If you want to add a new chapter, section, or significant functionality, please follow this flow:

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Releases and Versioning

We use [GitHub Releases](https://github.com/RonsGit/DL4CV/releases) for versioning.

* **Tags** are used to mark significant updates or stable milestones of the book.
* Check the tags to download specific historical versions of the PDF/text.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Contact and Feedback

I actively seek and value your feedback. Whether you are a student, researcher, or practitioner, your insights help make this resource better for everyone.

* **Found a mistake?**
* **Have a request for a new topic?**
* **Problem with credits or references?**
* **Want to reach out privately?**

Please do not hesitate to reach out:

1. **Email**: For private communication, you can reach me at [eecs498summary@gmail.com](mailto:eecs498summary@gmail.com).
2. **Open an Issue**: For specific problems, suggestions, or public discussion. [Click here to open an issue](https://github.com/RonsGit/DL4CV/issues).
3. **Pull Requests**: Direct fixes are always welcome.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Contributors

A huge thank you to everyone who has contributed to this project!

<a href="https://github.com/RonsGit/DL4CV/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=RonsGit/DL4CV" alt="contrib.rocks infinite contributors list" />
</a>

*Partial list of contributors. For specific credits regarding content, specially made figures, please see the **Preface** of the book/website.*

<p align="right">(<a href="#readme-top">back to top</a>)</p>

---

## Acknowledgments & Credits

This book stands on the shoulders of giants. A significant portion of this material is based on:

* **EECS498 (University of Michigan)** by Justin Johnson.
* Seminal papers and works by countless researchers in the Computer Vision community.

**Bibliography & Citations:**
We strive to maintain an accurate and up-to-date bibliography, crediting all images, papers, and ideas to their original authors. However, given the vast amount of material, mistakes can happen.
* **If you identify a missing credit, incorrect citation, or uncredited image:** Please contact us immediately (via Issue or Email), and we will correct it as quickly as possible.

The goal of this project is not to claim ownership of these ideas, but to cover them and make them accessible to a wider audience.

* [Justin Johnson](https://web.eecs.umich.edu/~justincj/)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

[contributors-shield]: https://img.shields.io/github/contributors/RonsGit/DL4CV.svg?style=for-the-badge
[contributors-url]: https://github.com/RonsGit/DL4CV/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/RonsGit/DL4CV.svg?style=for-the-badge
[forks-url]: https://github.com/RonsGit/DL4CV/network/members
[stars-shield]: https://img.shields.io/github/stars/RonsGit/DL4CV.svg?style=for-the-badge
[stars-url]: https://github.com/RonsGit/DL4CV/stargazers
[issues-shield]: https://img.shields.io/github/issues/RonsGit/DL4CV.svg?style=for-the-badge
[issues-url]: https://github.com/RonsGit/DL4CV/issues
[license-shield]: https://img.shields.io/github/license/RonsGit/DL4CV.svg?style=for-the-badge
[license-url]: https://github.com/RonsGit/DL4CV/blob/main/LICENSE
