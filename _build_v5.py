#!/usr/bin/env python3
"""Build film_stock_prompt_v5.json from v4, preserving good content + scaffolding new decks."""
import json, copy, sys
from pathlib import Path

V4 = Path("film_stock_prompt_v4.json")
V5 = Path("film_stock_prompt_v5.json")

data = json.loads(V4.read_text("utf-8"))
decks = data["decks"]

# ---------------------------------------------------------------------------
# Helper: add a new set to a deck
# ---------------------------------------------------------------------------
def new_set(name, abbr, description, bp_pos="", bp_neg="",
            prompts=None, prompt_template=None):
    """Create a set skeleton. If prompt_template is given, generate 50 from it."""
    neg_default = (
        "noise, film grain, analog noise, dithering, pointillism, grit, dust, "
        "scratches overlays, low quality, low resolution, jpeg artifacts, "
        "chromatic aberration, watercolor, oil painting, illustration, anime, "
        "cartoon, comic look, vector art, 3d render, octane render, cgsociety, "
        "beauty filter, plastic skin, waxy skin, doll-like, "
        "global gaussian blur, visible text, logos, watermarks"
    )
    entry = {
        "name": name,
        "abbr": abbr,
        "description": description,
        "boilerplate": {
            "positive": bp_pos or "",
            "negative": bp_neg or neg_default,
        },
        "prompts": prompts if prompts else (prompt_template or []),
    }
    # If we have a template but not real prompts, pad with 50 copies
    if prompt_template and not prompts:
        entry["prompts"] = [copy.deepcopy(prompt_template) for _ in range(50)]
    if not entry["prompts"]:
        entry["prompts"] = []
    return entry

# ---------------------------------------------------------------------------
# Preserve existing decks exactly
# ---------------------------------------------------------------------------
existing = {
    d.get("display_name") or d.get("model_name"): d
    for d in decks
}

# ---------------------------------------------------------------------------
# Final deck list (order matters)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# New deck descriptions and empty sets (defined BEFORE use)
# ---------------------------------------------------------------------------
def _deck_desc(name):
    descs = {
        "Nature and Wildlife": 
            "A collection of nature and wildlife photographs spanning landscapes, animal portraiture, "
            "macro flora, and underwater scenes. Tests organic texture rendering, natural color palettes "
            "(greens, browns, sky blues, earthy ochres), dynamic range in outdoor lighting, and the "
            "rendering of fur, feather, leaf, and water textures across diverse natural environments.",
        "Sports and Action":
            "A collection of sports and action photography capturing athletes in motion, frozen peak action, "
            "and the emotional theatre of competition. Tests motion blur rendering, frozen-motion sharpness, "
            "stadium lighting challenges, skin texture under exertion, and the dynamic range needed to "
            "capture both highlight-lit athletes and deep-shadow crowd backgrounds.",
        "Still Life and Product":
            "A collection of still life and product photography exploring controlled compositions of glass, "
            "metal, fabric, ceramic, organic matter, and liquids. Tests material rendering fidelity, color "
            "accuracy across the spectrum, specular highlight control, depth of field rendering, and the "
            "subtle tonal gradations needed to distinguish similar surface qualities under precise lighting.",
    }
    return descs.get(name, f"A collection of high-quality {name.lower()} photographs.")

def _empty_set(dname, idx):
    themes = _all_new_themes()
    name, abbr, desc = themes[dname][idx]
    return new_set(name, abbr, desc)

def _all_new_themes():
    return {
        "Nature and Wildlife": [
            ("Forest Canopy and Dappled Light", "ForestCanopy",
             "Forest scenes with light filtering through tree canopies, creating complex shadow patterns, "
             "god rays, and shifting pockets of illumination on the forest floor."),
            ("Mountain Majesty and Atmospheric Perspective", "MountainMajesty",
             "Mountain landscapes with layered ranges receding into haze, testing atmospheric perspective, "
             "snow texture, rock detail, and the subtle color shifts of distant peaks."),
            ("Water's Edge and Reflections", "WatersEdge",
             "Lakes, streams, and coastal edges where water meets land. Tests reflection rendering, "
             "transparency, rippled surfaces, and the color of water in varying depths and light."),
            ("Macro Flora and Botanical Precision", "MacroFlora",
             "Extreme close-ups of flowers, leaves, and botanical structures. Tests fine detail rendering, "
             "petal translucency, vein patterns, dewdrop refraction, and organic color gradients."),
            ("Big Cat Gaze and Predator Portrait", "BigCatGaze",
             "Animal portraiture of big cats and predators. Tests fur texture rendering, eye detail and "
             "catchlights, whisker sharpness, and the subtle color variations in animal coats."),
            ("Bird in Flight and Feather Detail", "BirdFlight",
             "Birds caught in motion — taking off, landing, soaring. Tests feather texture, wing dynamics, "
             "motion blur at wingtips vs sharp eye focus, and sky color rendering at different times of day."),
            ("Ocean Depths and Underwater Light", "OceanDepths",
             "Underwater scenes testing color absorption through water columns, caustic light patterns, "
             "marine life texture, and the unique quality of light filtered through a water surface."),
            ("Insect Architecture and Micro Detail", "InsectArch",
             "Extreme macro photography of insects. Tests the rendering of chitin textures, compound eyes, "
             "hair-thin leg details, wing veining, and the depth of field challenges of extreme close-up work."),
            ("Desert Solitude and Sand Stone", "DesertSolitude",
             "Desert landscapes emphasizing sand texture, rock formations, heat haze, and the extreme dynamic "
             "range of harsh midday sun against deep blue sky. Tests warm-earth color rendering."),
            ("Seasonal Transitions in Autumn Palette", "SeasonalTransitions",
             "Autumn landscapes testing the rendering of warm seasonal colors — golds, oranges, deep reds, "
             "browns — in foggy mornings, golden-hour forests, and the soft, diffused light of overcast days."),
        ],
        "Sports and Action": [
            ("Split-Second Frozen Motion", "SplitSecond",
             "Peak-action frozen motion — water droplets suspended mid-splash, athletes caught at the apex "
             "of a jump, impact moments where every detail is frozen in time."),
            ("Speed Lines and Panning Blur", "SpeedLines",
             "Panning shots following a moving subject while the background blurs into speed lines. "
             "Tests the balance between a sharp subject and directional motion blur."),
            ("Stadium Drama and Epic Wide", "StadiumDrama",
             "Wide shots of stadiums capturing competition space scale, geometry, and energy. "
             "Tests crowd rendering, architectural symmetry, floodlight patterns."),
            ("Pre-Competition Tension and Athlete Portrait", "PreCompetition",
             "Intimate portraits of athletes before competition — focus, anxiety, ritual preparation. "
             "Tests skin texture under varied locker-room and tunnel lighting."),
            ("Body in Motion and Athletic Form", "BodyMotion",
             "Peak athletic form — runners mid-stride, gymnasts in rotation, swimmers at full reach. "
             "Tests muscle definition, fabric movement, sweat on skin, dynamic energy."),
            ("Water Sports and Splash Spray", "WaterSports",
             "Water-based sports — swimming, diving, water polo, surfing. Tests water spray, caustic "
             "pool light, droplet sharpness, skin-water interaction under bright light."),
            ("Night Game and Floodlit Action", "NightGame",
             "Nighttime sports under floodlights. Tests mixed color temperature, shadow detail in "
             "unlit areas, highlight control on reflective surfaces."),
            ("Combat Sport and Grit Sweat", "CombatSport",
             "Boxing, wrestling, martial arts close-up action. Tests impact rendering, sweat, "
             "skin distortion, raw texture under harsh ring lighting."),
            ("Extreme Sport and Mountain Sky", "ExtremeSports",
             "Climbing, skiing, BASE jumping in mountain environments. Tests action against vast "
             "natural backgrounds, snow texture, ice detail, dual exposure challenges."),
            ("Victory and Defeat in Emotional Release", "VictoryDefeat",
             "Post-competition emotion — celebration, exhaustion, defeat, triumph. Tests genuine "
             "human emotion, tears, exertion-reddened skin, embrace, collapse."),
        ],
        "Still Life and Product": [
            ("Glass and Crystal Refraction", "GlassCrystal",
             "Glass objects lit to emphasize refraction, reflection, and transparency. Tests light "
             "bending through transparent materials, caustic patterns, subtle edge definition."),
            ("Metallic Lustre and Chrome Steel", "MetallicLustre",
             "Polished metal objects — chrome, steel tools, silverware, brass. Tests specular "
             "highlights, metallic gradients, environmental reflections, brushed vs polished finish."),
            ("Fabric Folds and Drapery Study", "FabricFolds",
             "Classical drapery study — cloth folded, draped, bunched, hanging. Tests fabric weave, "
             "fold geometry, highlight and shadow along creases, tonal gradations of volume."),
            ("Culinary Art and Food Plating", "CulinaryArt",
             "Fine dining plated dishes. Tests food texture, sauce gloss, vegetable color saturation, "
             "meat sear detail, steam, ingredient surface qualities under restaurant lighting."),
            ("Floral Arrangement and Botanical Precision", "FloralArrangement",
             "Floral still life with arranged blooms and greenery. Tests petal translucency, stamen "
             "detail, leaf vein rendering, water droplets, full-spectrum flower colors."),
            ("Vintage Objects and Patina Age", "VintageObjects",
             "Aged objects — rusted tools, tarnished silver, weathered leather, chipped ceramics. "
             "Tests surface wear, patina, corrosion, subtle color shifts of age and use."),
            ("Liquid in Motion and Pour Splash", "LiquidMotion",
             "Liquids in motion — pouring, splashing, dripping. Tests droplet rendering, surface "
             "tension, splash geometry, bubble detail, different fluid optical behaviors."),
            ("Tool and Craft Workshop Detail", "ToolCraft",
             "Workshop still life with tools and materials. Tests diverse materials in one frame — "
             "wood grain, metal patina, leather, paint, sawdust — under practical lighting."),
            ("Light and Shadow Single Source", "LightShadow",
             "Chiaroscuro still life with single dramatic light source. Tests deep shadow detail "
             "retention, highlight-to-black falloff, sculptural quality defined by light alone."),
            ("Minimalist White on White", "MinimalistWhite",
             "High-key minimalist still life with white objects on white. Tests subtle tonal separations "
             "in near-white values, distinguishing white materials, highlight detail without burnout."),
        ],
    }

DECK_ORDER = [
    "Photojournalism",           # 10 sets ✓
    "Studio (1950s-1970s)",      # 8 → 10
    "World View",                # 8 → 10
    "1930s-1940s Cinema",        # 8 → 10
    "Bouidoir and Intimate Portraiture",  # 8 → 10 (note: typo in v4 data)
    "Pinup and Bikini",          # 9 → 10
    "Classic Nudes",             # 10 ✓
    "Nature and Wildlife",       # NEW
    "Sports and Action",         # NEW
    "Still Life and Product",    # NEW
]

new_decks = []

for dname in DECK_ORDER:
    if dname in existing:
        d = copy.deepcopy(existing[dname])
        cur_sets = d["sets"]
        cur_count = len(cur_sets)
        
        # Pad to 10 sets
        if dname == "Photojournalism":
            pass  # already 10
        elif dname == "Classic Nudes":
            pass  # already 10
        elif dname == "Pinup and Bikini":
            # Has 9, add 1
            cur_sets.append(new_set(
                "Desert Sun and Shadows (Dunes and Heat)",
                "DesertSun",
                "Pinup and bikini scenes in desert landscapes, testing harsh sunlight rendering, "
                "heat haze, sand texture, and the interplay of shadows on dunes. High contrast, "
                "deep shadows, and the challenge of rendering skin tones in intense midday light "
                "with strong color saturation against warm earth tones."
            ))
        elif dname == "Studio (1950s-1970s)":
            cur_sets.append(new_set(
                "Cine Lighting (Rembrandt and Loop)",
                "CineLighting",
                "Classic portrait lighting patterns including Rembrandt triangle and loop lighting, "
                "testing highlight-to-shadow transitions across skin tones and fabric textures. "
                "Controlled studio conditions with precise key/fill ratios, catchlight shaping, "
                "and the subtle gradation from bright highlight to deep core shadow."
            ))
            cur_sets.append(new_set(
                "Tabletop Product (Precision Still)",
                "TabletopProduct",
                "Controlled tabletop product photography testing material rendering, color accuracy, "
                "and specular highlight control. Small-scale studio setups with glass, metal, ceramic, "
                "and textile objects arranged in precise compositions with carefully flagged lighting."
            ))
        elif dname == "World View":
            cur_sets.append(new_set(
                "Aerial Drone Perspective",
                "AerialDrone",
                "Top-down and high-angle aerial photography from drone heights, testing depth rendering, "
                "atmospheric perspective, and the ability to resolve detail at extreme distances. "
                "Landscapes, urban grids, agricultural patterns, and coastlines viewed from above."
            ))
            cur_sets.append(new_set(
                "Night City (Available Darkness)",
                "NightCity",
                "Urban night photography using only available light sources — streetlamps, neon signs, "
                "car headlights, lit windows. Tests shadow detail retention, highlight bloom control, "
                "color temperature mixing (warm sodium vs cool LED), and the rendering of deep shadows "
                "that still hold environmental information."
            ))
        elif dname == "1930s-1940s Cinema":
            cur_sets.append(new_set(
                "Technicolor Dream (Saturated Palette)",
                "TechnicolorDream",
                "Vibrant three-strip Technicolor aesthetics from classic Hollywood, testing full-spectrum "
                "color rendering with rich, saturated primaries. Deep reds, vivid blues, lush greens, "
                "and golden ambers in carefully composed mise-en-scène. The challenge is rendering saturated "
                "color without losing tonal separation or creating digital-looking chroma."
            ))
            cur_sets.append(new_set(
                "Newsreel Documentary Grit",
                "NewsreelGrit",
                "Documentary-style 1940s newsreel aesthetic, testing handheld camera feel, variable exposure, "
                "and the look of on-location cinematography. Gritty urban scenes, wartime imagery, "
                "pressed-crowd shots, and spontaneous documentary moments with the visual texture "
                "of period newsreel footage."
            ))
        elif dname == "Bouidoir and Intimate Portraiture":
            cur_sets.append(new_set(
                "Textiles and Touch (Fabric Study)",
                "TextilesTouch",
                "Boudoir studies emphasizing the tactile interaction between skin and various fabrics — silk, "
                "lace, velvet, satin, wool, linen. Tests material texture rendering, the subtle color shifts "
                "where fabric meets skin, and the ability to distinguish between different fabric weaves "
                "through lighting alone."
            ))
            cur_sets.append(new_set(
                "Abstract Form (Fragmented Portrait)",
                "AbstractForm",
                "Boudoir as abstract composition — extreme crops, partial views, limbs curving out of frame, "
                "bodies fragmented by shadow and light. Tests the model's ability to render implied forms "
                "and continue anatomical logic beyond the visible frame. No faces, no full figures — "
                "pure sculptural abstraction."
            ))
        elif dname == "Pinup and Bikini":
            pass  # already added above
        
        d["sets"] = cur_sets[:10]  # cap at 10
        new_decks.append(d)
    
    else:
        # New deck — scaffold with 10 empty sets
        n = dname.lower().replace(" ", "-")
        d = {
            "model_name": dname,
            "display_name": dname,
            "description": _deck_desc(dname),
            "sets": [_empty_set(dname, i) for i in range(10)],
        }
        new_decks.append(d)



# ---------------------------------------------------------------------------
# Rebuild wrapper
# ---------------------------------------------------------------------------
output = {"decks": new_decks}

V5.write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
print(f"Wrote {V5}")
print(f"Decks: {len(new_decks)}")
prompts_total = sum(
    len(s.get("prompts", []))
    for d in new_decks
    for s in d.get("sets", [])
)
print(f"Total sets: {sum(len(d.get('sets',[])) for d in new_decks)}")
print(f"Total prompts: {prompts_total}")