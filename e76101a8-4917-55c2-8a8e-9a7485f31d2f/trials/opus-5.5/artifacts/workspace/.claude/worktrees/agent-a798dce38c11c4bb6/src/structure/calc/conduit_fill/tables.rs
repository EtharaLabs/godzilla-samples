//! The makers' catalogues behind `conduit_fill`: the outside diameter of the flexible 750 V PVC
//! cable (Corfio) of each section, and each conduit family's sizes with their inside diameter
//! (the outside less twice the wall), with the document, page and address they come from.

/// The sections the cable catalogue has, mm², and the cable's outside diameter, mm.
pub const CABLES: [(f64, f64); 18] = [
    (0.5, 2.15),
    (0.75, 2.35),
    (1.0, 2.5),
    (1.5, 2.95),
    (2.5, 3.55),
    (4.0, 4.05),
    (6.0, 4.65),
    (10.0, 6.0),
    (16.0, 7.0),
    (25.0, 8.6),
    (35.0, 10.15),
    (50.0, 11.8),
    (70.0, 13.5),
    (95.0, 15.7),
    (120.0, 17.2),
    (150.0, 19.1),
    (185.0, 21.4),
    (240.0, 24.2),
];

/// A family of conduits: its key, where its dimensions come from, and its sizes (mark, inside
/// diameter in mm) from the smallest.
pub struct Family {
    pub key: &'static str,
    pub document: &'static str,
    pub maker: &'static str,
    pub page: &'static str,
    pub url: &'static str,
    pub sizes: &'static [(&'static str, f64)],
}

const WAVIN: &str = "https://mediahub.wavin.com/m/2159cf9811cfe732/original/-FT-Eletroduto-Soldavel-e-Roscavel.pdf";
const WAVIN_DOC: &str = "Ficha técnica \"Eletroduto Rígido Soldável e Roscável\"";
const ELECON: &str = "https://elecon.com.br/wp-content/uploads/2017/10/catalogo.pdf";
const ELECON_DOC: &str = "Catálogo Elecon (Eletrodutos)";

pub const FAMILIES: [Family; 4] = [
    Family {
        key: "pvc-thread",
        document: WAVIN_DOC,
        maker: "Amanco Wavin Eletroduto rígido roscável",
        page: "8 and 9 (outside diameter B (dem) and wall C)",
        url: WAVIN,
        sizes: &[
            ("1/2\"", 16.4),
            ("3/4\"", 21.6),
            ("1\"", 27.5),
            ("1.1/4\"", 35.9),
            ("1.1/2\"", 41.4),
            ("2\"", 52.7),
            ("2.1/2\"", 67.3),
            ("3\"", 79.6),
            ("4\"", 103.9),
        ],
    },
    Family {
        key: "pvc-solder",
        document: WAVIN_DOC,
        maker: "Amanco Wavin Eletroduto rígido soldável",
        page: "6 (diameter B and wall C)",
        url: WAVIN,
        sizes: &[("DN20", 16.8), ("DN25", 21.4), ("DN32", 27.8)],
    },
    Family {
        key: "steel-heavy",
        document: ELECON_DOC,
        maker: "Elecon Eletroduto eletrolítico pesado, NBR 13057",
        page: "5 (wall and outside diameter, minimum and maximum)",
        url: ELECON,
        sizes: &[
            ("1/2\"", 17.0),
            ("3/4\"", 22.2),
            ("1\"", 28.5),
            ("1.1/4\"", 36.5),
            ("1.1/2\"", 42.1),
            ("2\"", 53.9),
            ("2.1/2\"", 68.8),
            ("3\"", 81.5),
            ("4\"", 106.3),
        ],
    },
    Family {
        key: "steel-rir",
        document: ELECON_DOC,
        maker: "Elecon Eletroduto RIR galvanizado a fogo, NBR 5597 (rosca NPT)",
        page: "7 (outside diameter and wall)",
        url: ELECON,
        sizes: &[
            ("1/2\"", 16.8),
            ("3/4\"", 22.4),
            // 33.7 less twice 2.65, as the floats give it
            ("1\"", 28.400000000000002),
            ("1.1/4\"", 36.4),
            ("1.1/2\"", 42.3),
            ("2\"", 53.6),
            ("2.1/2\"", 65.5),
            ("3\"", 81.4),
            ("4\"", 105.8),
            ("5\"", 131.3),
            ("6\"", 157.7),
        ],
    },
];
