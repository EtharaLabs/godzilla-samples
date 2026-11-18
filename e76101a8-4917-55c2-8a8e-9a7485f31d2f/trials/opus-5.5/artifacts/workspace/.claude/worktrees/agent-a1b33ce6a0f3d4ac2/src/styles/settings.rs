//! Project settings: `units`, `room_area`, `language`, `standard`.
//!
//! The project's display units (the model and every command keep millimetres), where it measures
//! its rooms' areas, the language its drawings speak, and its technical standard, which adapts
//! line weights, object styles and units when it is set.

use super::common::R;
use super::weights::{self, flag, Pens, Weights};
use crate::json::Value;
use crate::project::Project;
use crate::session::Session;

pub fn run(s: &mut Session, cid: &str, p: &Value) -> R<Value> {
    match cid {
        "units" => units(&mut s.project, p),
        "room_area" => room_area(&mut s.project, p),
        "language" => language(&mut s.project, p),
        "standard" => standard(&mut s.project, p),
        _ => Err(format!("{}: not supported here", cid)),
    }
}

/// What `inspect` says of the settings: the model's units (always mm), the project's units, where
/// rooms are measured and the standard (the project's language is the core's own key).
pub fn inspect_entries(s: &Session, out: &mut Vec<(String, Value)>) {
    let pr = &s.project;
    out.push(("units".into(), Value::s("mm")));
    out.push(("project_units".into(), Value::s(&weights::project_units(pr))));
    out.push(("room_area".into(), Value::s(&room_area_of(pr))));
    out.push(("standard".into(), Value::s(standard_of(pr).code)));
}

/// A text parameter as these commands read it: None when absent or null; the text as given
/// (at most 256 characters).
fn text(p: &Value, cmd: &str, key: &str) -> R<Option<String>> {
    match p.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) if s.chars().count() <= 256 => Ok(Some(s.clone())),
        Some(v) => Err(format!("{}: `{}` must be text of at most 256 characters, got {}", cmd, key, v.to_compact())),
    }
}

// ---------------------------------------------------------------- units

pub const UNITS: &[&str] = &["mm", "cm", "m", "in", "ft", "ft-in"];

fn units(pr: &mut Project, p: &Value) -> R<Value> {
    if let Some(raw) = text(p, "units", "length")? {
        let code = raw.trim().to_lowercase();
        if !UNITS.contains(&code.as_str()) {
            return Err(format!("units: `length` is mm, cm, m, in, ft or ft-in, not `{}`", raw));
        }
        if weights::project_units(pr) != code {
            pr.insert_top("units", Value::s(&code));
        }
    }
    Ok(jobj! {"length" => weights::project_units(pr)})
}

// ---------------------------------------------------------------- room area

pub fn room_area_of(pr: &Project) -> String {
    pr.get("room_area").and_then(|v| v.as_str()).unwrap_or("centre").to_string()
}

fn room_area(pr: &mut Project, p: &Value) -> R<Value> {
    if let Value::Obj(m) = p {
        for (k, _) in weights::sorted_items(m) {
            if k != "at" {
                return Err(format!("room_area: `{}` isn't one of its parameters: at", k));
            }
        }
    }
    if let Some(v) = p.get("at") {
        let s = match v {
            Value::Str(s) => s,
            _ => return Err("room_area: `at` is centre or finish".into()),
        };
        if s.chars().count() > 256 {
            return Err(format!(
                "room_area: `at` must be text of at most 256 characters, got {}",
                v.to_compact()
            ));
        }
        match s.as_str() {
            "centre" => pr.remove_top("room_area"),
            "finish" => pr.insert_top("room_area", Value::s("finish")),
            _ => return Err(format!("room_area: `at` is centre or finish, not `{}`", s)),
        }
    }
    Ok(jobj! {"at" => room_area_of(pr)})
}

// ---------------------------------------------------------------- language

/// A language a project can speak, from its code or its name (en, pt-BR, Português, Dutch…).
pub fn parse_language(raw: &str) -> Option<&'static str> {
    let low = raw.trim().to_lowercase();
    let head = match low.find(|c| c == '-' || c == '_' || c == '.') {
        Some(i) => &low[..i],
        None => low.as_str(),
    };
    Some(match head {
        "en" | "english" => "en",
        "pt" | "português" | "portuguese" => "pt",
        "es" | "español" | "spanish" => "es",
        "sv" | "svenska" | "swedish" => "sv",
        "cs" | "čeština" | "cestina" | "czech" => "cs",
        "fr" | "français" | "francais" | "french" => "fr",
        "nl" | "nederlands" | "dutch" | "flemish" | "vlaams" => "nl",
        "de" | "deutsch" | "german" => "de",
        "it" | "italiano" | "italian" => "it",
        _ => return None,
    })
}

fn language(pr: &mut Project, p: &Value) -> R<Value> {
    if let Some(raw) = text(p, "language", "code")? {
        let code = parse_language(&raw)
            .ok_or_else(|| format!("language: `{}` is no language here; use en, pt, es or sv", raw))?;
        if pr.language() != code {
            pr.insert_top("language", Value::s(code));
        }
    }
    Ok(jobj! {"language" => pr.language()})
}

// ---------------------------------------------------------------- standards

pub struct Standard {
    pub code: &'static str,
    pub name: &'static str,
    pub short_name: &'static str,
    pub region: &'static str,
    pub description: &'static str,
    pub references: &'static [&'static str],
    pub governing_body: &'static str,
    pub projection: &'static str,
    pub default_sheet_size: &'static str,
    pub default_units: &'static str,
    /// The pens (seen, cut) it gives the categories it sets.
    pub styles: &'static [(&'static str, u64, u64)],
}

const ISO_STYLES: &[(&str, u64, u64)] = &[
    ("beam", 4, 10),
    ("ceiling", 4, 6),
    ("column", 4, 10),
    ("door", 4, 6),
    ("floor", 4, 10),
    ("footing", 4, 10),
    ("mass", 4, 4),
    ("railing", 6, 10),
    ("roof", 4, 10),
    ("stair", 4, 10),
    ("wall", 4, 10),
    ("window", 4, 6),
];

pub const STANDARDS: &[Standard] = &[
    Standard {
        code: "nbr",
        name: "Normas Brasileiras (ABNT / NBR)",
        short_name: "NBR",
        region: "Brasil",
        description: "Normas ABNT brasileiras completas: NBR 16861 (espessuras escalonadas em raiz de 2), NBR 16752 (margem esquerda de 25 mm para fixação, legenda de 178 mm), NBR 17006 (1º diedro), NBR 17067 (marcas de dobra para arquivamento A4), NBR 17068 (cotagem com ticks a 45° acima da linha) e NBR 6492 (hierarquia de alvenarias e elementos arquitetônicos cortados a 0.50 mm).",
        references: &[
            "NBR 16861: Desenho técnico — Requisitos para representação de linhas e escrita",
            "NBR 16752: Desenho técnico — Formatos de folhas de desenho e leiautes (Margem 25 mm)",
            "NBR 17006: Desenho técnico — Princípios gerais de representação (1º Diedro)",
            "NBR 17067: Desenho técnico — Dobramento de folhas (Módulo final A4)",
            "NBR 17068: Desenho técnico — Cotagem (Regras de linhas e texto)",
            "NBR 6492: Documentação técnica para projetos arquitetônicos",
        ],
        governing_body: "ABNT — Associação Brasileira de Normas Técnicas",
        projection: "1st Angle (1º Diedro)",
        default_sheet_size: "A1",
        default_units: "m",
        styles: &[
            ("beam", 5, 12),
            ("ceiling", 3, 7),
            ("column", 5, 12),
            ("door", 3, 7),
            ("floor", 4, 10),
            ("footing", 5, 10),
            ("mass", 5, 5),
            ("railing", 5, 7),
            ("roof", 5, 10),
            ("stair", 5, 10),
            ("wall", 4, 10),
            ("window", 3, 7),
        ],
    },
    Standard {
        code: "iso",
        name: "International Organization for Standardization (ISO)",
        short_name: "ISO",
        region: "International / Global",
        description: "Normas técnicas internacionais ISO: ISO 128 (grupo métrico de espessuras de linha, 1º ângulo), ISO 5457 (folhas métricas A0 a A4 com margem de arquivamento de 20 mm), ISO 129-1 (cotagem métrica com setas cheias ou traços), e ISO 7200 (legenda de 180 mm).",
        references: &[
            "ISO 128: Technical product documentation — General principles of representation",
            "ISO 5457: Technical product documentation — Sizes and layout of drawing sheets",
            "ISO 129-1: Technical product documentation — Presentation of dimensions and tolerances",
            "ISO 7200: Technical product documentation — Data fields in title blocks",
            "ISO 3098: Technical product documentation — Lettering",
            "ISO 7518 / ISO 7519: Technical drawings — Construction drawings",
        ],
        governing_body: "ISO — International Organization for Standardization",
        projection: "1st Angle (1º Diedro)",
        default_sheet_size: "A3",
        default_units: "mm",
        styles: ISO_STYLES,
    },
    Standard {
        code: "ansi",
        name: "American National Standards (ANSI / ASME / AIA)",
        short_name: "ANSI",
        region: "United States",
        description: "Padrões americanos ANSI / ASME / AIA: ASME Y14.2 (espessuras em polegadas e NCS), ASME Y14.1 / AIA (formatos arquitetônicos Arch D, Arch C, Arch E e ANSI A-E), ASME Y14.5 (projeção no 3º diedro, cotagem com texto centralizado ou sobre a linha), unidades em pés e polegadas fracionárias (ft-in).",
        references: &[
            "ASME Y14.2: Line Conventions and Lettering",
            "ASME Y14.1 / Y14.1M: Drawing Sheet Size and Format (Arch & ANSI)",
            "ASME Y14.5: Dimensioning and Tolerancing (3rd Angle Projection)",
            "AIA CAD Guidelines: Layer Guidelines, Line Weights, and Sheet Layouts",
            "United States National CAD Standard (NCS)",
        ],
        governing_body: "ANSI / ASME / AIA (American Institute of Architects)",
        projection: "3rd Angle (3º Diedro)",
        default_sheet_size: "ARCH D",
        default_units: "ft-in",
        styles: &[
            ("beam", 4, 11),
            ("ceiling", 2, 6),
            ("column", 5, 11),
            ("door", 2, 6),
            ("floor", 4, 8),
            ("footing", 4, 9),
            ("mass", 4, 4),
            ("railing", 4, 7),
            ("roof", 4, 10),
            ("stair", 4, 9),
            ("wall", 4, 10),
            ("window", 2, 6),
        ],
    },
    Standard {
        code: "eu",
        name: "European Standards (CEN / EN / Eurocodes)",
        short_name: "EN/EU",
        region: "European Union",
        description: "Normas europeias harmonizadas EN ISO e Eurocodes: EN ISO 128 e 5457 (formatos métricos, 1º diedro, margem de arquivamento de 20 mm), EN ISO 129 (cotagem com vírgula decimal) e regras construtivas dos Eurocodes.",
        references: &[
            "EN ISO 128: Princípios gerais de representação técnica",
            "EN ISO 5457: Formatos e leiautes de folhas de desenho",
            "EN ISO 129: Indicação de cotas e tolerâncias",
            "EN ISO 7200: Campos de dados em legendas de desenho",
            "EN 1990 — EN 1999: Eurocodes (Regras de dimensionamento e documentação)",
        ],
        governing_body: "CEN — European Committee for Standardization",
        projection: "1st Angle (1º Diedro)",
        default_sheet_size: "A3",
        default_units: "mm",
        styles: ISO_STYLES,
    },
    Standard {
        code: "jis",
        name: "Japanese Industrial Standards (JIS)",
        short_name: "JIS",
        region: "Japan",
        description: "Normas industriais japonesas (JIS): JIS Z 8310 e JIS A 0150 (projeção no 3º diedro, formatos métricos A0 a A4, espessuras métricas padronizadas).",
        references: &[
            "JIS Z 8310: Princípios gerais de desenho técnico",
            "JIS B 0001: Desenho técnico e documentação mecânica",
            "JIS A 0150: Desenhos para arquitetura e construção",
        ],
        governing_body: "JISC — Japanese Industrial Standards Committee",
        projection: "3rd Angle (3º Diedro)",
        default_sheet_size: "A3",
        default_units: "mm",
        styles: ISO_STYLES,
    },
];

/// A standard from its code or one of its other names.
pub fn parse_standard(raw: &str) -> Option<&'static Standard> {
    let code = match raw.trim().to_lowercase().as_str() {
        "nbr" | "abnt" | "brasil" | "brazil" => "nbr",
        "iso" | "international" => "iso",
        "ansi" | "asme" | "aia" | "us" | "usa" => "ansi",
        "eu" | "en" | "europe" => "eu",
        "jis" | "japan" => "jis",
        _ => return None,
    };
    STANDARDS.iter().find(|s| s.code == code)
}

/// The project's standard (ISO unless its file names another).
pub fn standard_of(pr: &Project) -> &'static Standard {
    let code = pr.get("standard").and_then(|v| v.as_str()).unwrap_or("iso");
    STANDARDS.iter().find(|s| s.code == code).unwrap_or(&STANDARDS[1])
}

/// The line weights a standard sets.
pub fn standard_weights(st: &Standard) -> Weights {
    match st.code {
        "nbr" => Weights { model: weights::NBR.to_vec(), annotation: weights::NBR_ANNOTATION },
        "ansi" => Weights { model: weights::IMPERIAL.to_vec(), annotation: weights::ANNOTATION },
        _ => Weights { model: weights::METRIC.to_vec(), annotation: weights::ANNOTATION },
    }
}

fn strs(v: &[&str]) -> Value {
    Value::Arr(v.iter().map(|s| Value::s(s)).collect())
}

fn standard_listing(pr: &Project) -> Value {
    let all: Vec<Value> = STANDARDS
        .iter()
        .map(|s| {
            jobj! {
                "code" => s.code,
                "description" => s.description,
                "name" => s.name,
                "references" => strs(s.references),
                "region" => s.region,
                "short_name" => s.short_name,
            }
        })
        .collect();
    let st = standard_of(pr);
    jobj! {
        "all" => Value::Arr(all),
        "default_sheet_size" => st.default_sheet_size,
        "default_units" => st.default_units,
        "governing_body" => st.governing_body,
        "name" => st.name,
        "projection" => st.projection,
        "references" => strs(st.references),
        "region" => st.region,
        "short_name" => st.short_name,
        "standard" => st.code,
    }
}

fn standard(pr: &mut Project, p: &Value) -> R<Value> {
    const C: &str = "standard";
    let raw = match text(p, C, "set")? {
        Some(r) => r,
        None => return Ok(standard_listing(pr)),
    };
    let st = parse_standard(&raw).ok_or_else(|| format!("{}: `set` is nbr, iso, ansi, eu or jis, not `{}`", C, raw))?;
    let all = flag(p, C, "adapt_all")?.unwrap_or(true);
    let lw = flag(p, C, "adapt_line_weights")?.unwrap_or(all);
    let os = flag(p, C, "adapt_object_styles")?.unwrap_or(all);
    let un = flag(p, C, "adapt_units")?.unwrap_or(all);
    if un {
        let cur = weights::project_units(pr);
        if weights::imperial(&cur) != weights::imperial(st.default_units) {
            pr.insert_top("units", Value::s(st.default_units));
        }
    }
    if lw {
        weights::set_own(pr, &standard_weights(st));
    }
    pr.insert_top("standard", Value::s(st.code));
    if os {
        for (cat, projection, cut) in st.styles {
            weights::put_style(pr, cat, Pens { projection: *projection, cut: *cut });
        }
    }
    // setting a standard is a step of its own, though it was the project's already
    super::mark_step();
    Ok(standard_listing(pr))
}
