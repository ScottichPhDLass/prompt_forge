#!/usr/bin/env python3
"""Fill empty prompt sets in film_stock_prompt_v5.json with 50 creative prompts each."""
import json, random
from pathlib import Path

V5 = Path("film_stock_prompt_v5.json")
data = json.loads(V5.read_text("utf-8"))
random.seed(42)

SHOT_TYPES = [
    "close-up", "extreme close-up", "medium shot", "medium-long shot",
    "wide shot", "establishing shot", "overhead shot", "high-angle shot",
    "low-angle shot", "three-quarter portrait", "full-body shot", "macro shot",
]

def neg(*extras):
    base = ("noise, film grain, analog noise, dithering, pointillism, grit, dust, "
            "scratches overlays, low quality, low resolution, jpeg artifacts, "
            "chromatic aberration, watercolor, oil painting, illustration, anime, "
            "cartoon, comic look, vector art, 3d render, octane render, cgsociety, "
            "beauty filter, plastic skin, waxy skin, doll-like, "
            "global gaussian blur, visible text, logos, watermarks")
    extras = [e for e in extras if e]
    return base + ", " + ", ".join(extras) if extras else base


# ===========================================================================
# PROMPT GENERATORS — each returns a list of 50 [positive, negative] pairs
# ===========================================================================

GENS = {}

# ---- Studio (1950s-1970s) -----------------------------------------------

def gen_cine_lighting():
    lights = ["Rembrandt lighting", "loop lighting", "split lighting", "butterfly lighting",
              "short lighting", "broad lighting", "clam shell lighting", "rim lighting"]
    subjects = [
        "a middle-aged man with sharp cheekbones and a strong jaw",
        "a woman with delicate features and expressive eyes",
        "an elderly musician with weathered hands and deep laugh lines",
        "a young actor with intense gaze and sculpted bone structure",
        "a fashion model with angular features and porcelain skin",
        "a veteran artisan with calloused hands and steady eyes",
        "a dancer with a graceful neck and defined collarbones",
        "a professor with silver hair and thoughtful eyes",
        "a chef with a warm smile and flour-dusted apron",
        "a subject with freckled skin and copper hair",
    ]
    angles = ["above and left", "above and right", "straight on elevated", "low and angled"]
    effects = [
        "a distinct triangle of light on the shadowed cheek",
        "a catchlight shaped by an octabox visible in both eyes",
        "a graduated falloff across the facial planes from highlight to core shadow",
        "a sharp demarcation between the lit and shadow sides of the face",
    ]
    details = [
        "Skin texture shows pores, fine hairs, and the natural topography of the face",
        "The texture of the collar and shoulder area shows weave detail in the lit zone",
        "Hair has individual strand definition where the key light catches it",
        "A subtle rim light separates the shadow side from the background",
    ]
    results = []
    for _ in range(50):
        s = random.choice(subjects)
        st = random.choice(SHOT_TYPES)
        l = random.choice(lights)
        a = random.choice(angles)
        e = random.choice(effects)
        d = random.choice(details)
        pos = (
            f"realistic photographic {st} of {s}, "
            f"lit with precise {l}, a single key light from {a} "
            f"creating {e}. "
            f"The background is a seamless mid-gray that gradates to darker edges. "
            f"{d}. "
            f"Highlight rolloff is smooth and natural, shadow detail retains "
            f"environmental information without blocking up."
        )
        results.append([pos, neg("flat even lighting with no shadow pattern",
                                 "diffused softbox with no directional quality")])
    return results

GENS["Studio (1950s-1970s)"] = {
    "Cine Lighting (Rembrandt and Loop)": gen_cine_lighting(),
}

# ---- Tabletop Product ---------------------------------------------------

def gen_tabletop():
    objects = [
        "a crystal decanter", "a polished brass compass", "a ceramic teapot",
        "a leather-bound journal", "a stainless steel coffee press", "a hand-thrown stoneware vase",
        "a vintage brass microscope", "a cut-glass perfume bottle", "a wooden music box",
        "an enameled cast iron pot", "a silver-plated tea service", "a marble mortar and pestle",
        "a porcelain figurine", "a copper measuring set", "a carved jade paperweight",
    ]
    surfaces = ["polished mahogany", "black marble", "raw linen", "weathered oak boards",
                "brushed aluminum", "dark slate", "cream matte paper", "honed granite", "aged leather"]
    backgrounds = [
        "a clean white sweep curving seamlessly into the table surface",
        "a gradient backdrop that shifts from charcoal to soft gray",
        "a shallow depth of field dissolving the background into soft bokeh",
        "a dark void isolating the object in space",
    ]
    lights = [
        "a single softbox at 45 degrees",
        "dual strip lights from each side",
        "a large octabank from above",
        "a gridded spot from behind creating rim light",
        "bookend fill with a white reflector opposite",
    ]
    textures = [
        "micro-scratches in the metal polished to a mirror finish",
        "the subtle orange-peel texture of kiln-fired glaze",
        "grain of the leather with natural scarring and patina",
        "the cold sharpness of faceted crystal edges with internal refraction",
        "the warm diffuse reflection of wood grain beneath hand-polished lacquer",
    ]
    temps = ["balanced at 5500K", "warm at 3200K tungsten", "cool at 6500K mimicking overcast daylight"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        surf = random.choice(surfaces)
        bg = random.choice(backgrounds)
        li = random.choice(lights)
        tx = random.choice(textures)
        t = random.choice(temps)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {obj} "
            f"resting on {surf}, photographed on {bg}. "
            f"Lighting from {li}. "
            f"The object's surface reveals every material truth: {tx}. "
            f"Specular highlights are precisely placed and shaped by the light modifier, "
            f"with smooth falloff and no clipping. Shadows are deep but hold detail in the "
            f"transition zones. Color temperature is {t}. "
            f"The composition follows the rule of thirds with careful negative space."
        )
        results.append([pos, neg("harsh uncontrolled reflections",
                                 "blown-out specular highlights",
                                 "chromatic aberration on edges",
                                 "oversharpened metal edges",
                                 "flat tabletop lighting")])
    return results

GENS["Studio (1950s-1970s)"]["Tabletop Product (Precision Still)"] = gen_tabletop()

# ---- World View ---------------------------------------------------------

def gen_aerial():
    subjects = [
        "a serpentine river cutting through dense green forest",
        "geometric patchwork of agricultural fields in harvest season",
        "a coastal cliff with waves breaking against the rock far below",
        "the concentric rings of a circular irrigation system",
        "a city grid at dawn with long shadows stretching from buildings",
        "a volcanic crater with steam rising from its center",
        "the abstract pattern of a salt flat with crystallization lines",
        "a cargo ship leaving a wake through turquoise shallows",
        "sand dunes stretching to the horizon with wind-carved ridges",
        "the intersection of a highway interchange at golden hour",
    ]
    hazes = ["slight blue-white haze", "warm dust-hazed atmosphere",
             "thin layer of coastal mist", "crisp clear air with no atmospheric distortion"]
    suns = [
        "the high sun creating minimal shadows and flat color fields",
        "low-angle morning sun stretching every shadow to reveal texture",
        "the golden hour casting long warm shadows diagonally across the frame",
        "overcast skies providing even, shadowless illumination across the entire area",
    ]
    details = ["individual trees in a canopy", "vehicles on roads",
               "the pattern of waves on water", "the texture of tilled soil",
               "the geometry of roof structures"]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        hz = random.choice(hazes)
        sn = random.choice(suns)
        dt = random.choice(details)
        pos = (
            f"realistic photographic overhead shot of {subj}, "
            f"captured from drone altitude directly above, the camera axis perpendicular to the ground. "
            f"Atmospheric perspective softens the distant edges with a {hz}. "
            f"Lighting from {sn}. "
            f"Color rendering captures the full palette of the scene with natural saturation. "
            f"Resolution is sufficient to distinguish fine ground detail: {dt}. "
            f"The frame contains no visible human presence, emphasizing pure geography."
        )
        results.append([pos, neg("visible drone shadows", "lens flare from sun in frame",
                                 "motion blur from drone movement",
                                 "oversaturated greens or blues",
                                 "compressed low-resolution aerial imagery")])
    return results

GENS["World View"] = {"Aerial Drone Perspective": gen_aerial()}

def gen_night_city():
    scenes = [
        "a rain-slicked intersection with neon reflections pooling on the asphalt",
        "a row of late-night storefronts with warm light spilling onto the sidewalk",
        "an elevated train platform with a single waiting passenger under fluorescent light",
        "the glowing windows of a high-rise apartment building against the night sky",
        "a taxi rank with headlight beams cutting through mist",
        "a bridge with streetlamps creating pools of orange light at regular intervals",
        "a night market stall with hanging bulbs illuminating stacked produce",
        "a parking garage with spiral ramps and cold fluorescent tubes",
        "a diner interior seen from outside through a steamed window",
        "an alleyway lit only by a single flickering sign and distant headlights",
    ]
    temps = [
        "warm sodium vapor streetlights at 2700K mixing with cool white LED storefronts at 5500K",
        "the deep blue of the twilight sky at 8000K contrasting with tungsten-lit windows at 3200K",
        "mercury vapor lamps casting a greenish-blue cast over the wet pavement",
        "mixed color temperatures from neon signs reflecting in puddles",
    ]
    surfs = [
        "wet pavement reflects the city glow with distorted streaks",
        "the brick wall soaks up light, revealing only its rough texture in the zones where light hits",
        "glass surfaces reflect the city in fragmented, colored shards",
        "metal surfaces catch sharp specular highlights from point light sources",
    ]
    atmos = ["thin mist that softens distant lights into glowing orbs",
             "clean crisp air that keeps every light source sharp and defined",
             "light drizzle that creates halos around every lamp"]
    results = []
    for _ in range(50):
        sc = random.choice(scenes)
        tp = random.choice(temps)
        sf = random.choice(surfs)
        at = random.choice(atmos)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {sc}, "
            f"shot at night using only available light. The color temperature is a complex mixture of {tp}. "
            f"Shadow detail is critical: the darkest areas must retain just enough information to suggest "
            f"depth and form without becoming featureless black. Highlights from direct light sources "
            f"are controlled with a natural bloom, not clipped. "
            f"Surface textures catch the light selectively: {sf}. "
            f"The atmosphere carries a {at}. "
            f"Deep shadows in the frame are deep but not empty, holding the information of the space beyond."
        )
        results.append([pos, neg("pure black shadows with no detail",
                                 "blown-out highlights on light sources",
                                 "flat uniform night lighting",
                                 "digital noise reduction that smears shadow detail",
                                 "unrealistic color casts")])
    return results

GENS["World View"]["Night City (Available Darkness)"] = gen_night_city()

# ---- 1930s-1940s Cinema -------------------------------------------------

def gen_technicolor():
    colors = [
        "crimson velvet drapes against emerald wallpaper, a woman in a sapphire dress",
        "golden amber light falling on a polished mahogany bar with amber liquors",
        "a turquoise swimming pool surrounded by white marble and scarlet bougainvillea",
        "an art deco ballroom with deep burgundy carpets, chrome fixtures, and champagne-light chandeliers",
        "a lush garden scene with crimson roses, violet wisteria, and bright green hedges in full sun",
        "a costume parlour with racks of ruby, jade, and gold fabrics cascading over each other",
    ]
    lights = ["studio-style three-point with strong key and fill",
              "dramatic with a single key light and deep colored shadows",
              "soft and diffuse with carefully controlled color temperature"]
    harmonies = ["complementary colors placed in adjacent planes",
                  "a single bold color accent against a neutral background",
                  "a progression of warm tones from foreground to background",
                  "cool shadows with warm highlights creating depth through color alone"]
    results = []
    for _ in range(50):
        c = random.choice(colors)
        li = random.choice(lights)
        h = random.choice(harmonies)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {c}, "
            f"shot in the style of three-strip Technicolor from the 1930s-1940s. "
            f"The color palette is deliberately saturated and theatrical, with primaries rendered at full intensity "
            f"without losing tonal separation. Reds are deep and rich without blocking up, "
            f"blues are vivid without turning cyan, greens are lush without going artificial. "
            f"Skin tones are warm and slightly bronzed, with the characteristic Technicolor glow. "
            f"Lighting is {li}. "
            f"The mise-en-scene is carefully composed with attention to color harmony: {h}. "
            f"Shadow areas carry subtle color information rather than going neutral black. "
            f"Textures are rendered with the characteristic slightly soft resolution of period color film: "
            f"sharp where it matters, softened in the background, with no digital edge enhancement."
        )
        results.append([pos, neg("desaturated or muted colors", "digital-looking chroma",
                                 "color bleeding across edges", "HDR-style color rendering",
                                 "modern flat color grading", "florescent color casts")])
    return results

GENS["1930s-1940s Cinema"] = {"Technicolor Dream (Saturated Palette)": gen_technicolor()}

def gen_newsreel():
    subjects = [
        "crowds gathered on a city street watching a military parade pass by",
        "a war correspondent speaking into a microphone, huddled in a trench coat",
        "factory workers streaming out of industrial gates at shift change",
        "a political rally with speakers on a wooden platform under harsh sun",
        "a displaced family walking along a rubble-strewn road with belongings in a cart",
        "a press conference with journalists crowding around a podium, flashbulbs popping",
        "dock workers unloading cargo from a freighter under a gray, overcast sky",
        "children playing in rubble, their clothes worn and shoes mismatched",
        "a field hospital tent with medical staff working by lantern light",
        "a train station packed with soldiers saying goodbye to loved ones",
    ]
    lights = ["harsh midday sun creating steep contrast",
              "overcast sky providing soft, even illumination",
              "the mixed light of street lamps and window light indoors",
              "the flat, colorless light of a winter afternoon"]
    frames = ["the edge of another photographer coat entering the frame",
              "a microphone boom entering from above",
              "a partial obstruction in the foreground creating depth",
              "grainy shadow areas where the film stock struggled with available light"]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        li = random.choice(lights)
        fr = random.choice(frames)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}, "
            f"shot in the aesthetic of 1940s newsreel cinematography. "
            f"The camera position feels organic and slightly imperfect, as if shot by a cameraman "
            f"on location with a handheld Eyemo or Bell and Howell. Exposure varies naturally across "
            f"the frame: the brightest areas approach but do not clip, and shadow areas hold just enough "
            f"detail to read the space. The tonal range is slightly compressed compared to modern film, "
            f"giving the image a characteristic period look. "
            f"Lighting is whatever the location provides: {li}. "
            f"Composition prioritizes information and emotional content over technical perfection. "
            f"The frame may include {fr}. "
            f"Faces show the wear of the era: weathered skin, hats pulled low, eyes squinting into the light. "
            f"There is no glamour here, only documentary truth. The image feels like a frame pulled from "
            f"a reel of 16mm black and white newsreel footage."
        )
        results.append([pos, neg("digital sharpness", "perfect exposure across the frame",
                                 "controlled studio lighting", "beauty lighting on faces",
                                 "clean edges with no halation", "modern color palette",
                                 "perfect composition")])
    return results

GENS["1930s-1940s Cinema"]["Newsreel Documentary Grit"] = gen_newsreel()

# ---- Boudoir ------------------------------------------------------------

def gen_textiles():
    fabrics = [
        "ivory silk charmeuse draping across bare shoulders, the fabric catching every highlight",
        "black lace against skin with intricate patterns casting shadows on the body beneath",
        "deep burgundy velvet pooling around a reclining form, the nap catching light in opposite directions",
        "cream angora wool soft against a collarbone, fine fibers catching point light",
        "emerald satin sheets tangled around limbs, the fabrics liquid sheen shifting with every fold",
        "ivory linen with visible weave texture, rough against smooth skin in soft window light",
        "crimson silk ribbon tied in a bow against the small of a back, satin edges catching rim light",
        "sheer ivory chiffon layered over skin, the fabrics transparency varying with distance and fold",
    ]
    lights = ["a large north-facing window creating soft directional light",
              "a single softbox placed to emphasize the fabric texture",
              "backlight that makes translucent fabrics glow at their edges",
              "a tungsten lamp casting warm light that brings out the fabric depth"]
    folds = ["tension folds radiating from where the fabric is gripped",
             "gravity folds hanging straight down from the shoulders",
             "bunched compression folds where the fabric is gathered",
             "the smooth stretched fabric over a curve with wrinkles radiating outward"]
    textures = [
        "the subtle sheen difference between warp and weft",
        "the nap of velvet reading darker against the grain",
        "the irregular slub texture of raw silk",
        "the geometric precision of lace pattern repeated across the surface",
    ]
    results = []
    for _ in range(50):
        fb = random.choice(fabrics)
        li = random.choice(lights)
        fl = random.choice(folds)
        tx = random.choice(textures)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {fb}. "
            f"The image is a study in textile rendering: the fabric must read as physically real, "
            f"with distinct weave, drape, and surface quality that separates it from skin. "
            f"Lighting from {li}. "
            f"The interaction between fabric and skin creates subtle color shifts where they meet: "
            f"the reflected color of the fabric tints the adjacent skin slightly. "
            f"Folds and creases in the fabric are rendered with clear geometric logic: {fl}. "
            f"The fabric surface shows {tx}. "
            f"Skin beneath the fabric or adjacent to it maintains natural texture: pores, fine hairs, "
            f"the subtle topography of the body, distinct from the fabrics surface."
        )
        results.append([pos, neg("fabric that looks painted or airbrushed",
                                 "skin and fabric with identical surface quality",
                                 "fabric folds that defy gravity",
                                 "plastic-looking lace",
                                 "CGI-quality satin sheen")])
    return results

def gen_abstract():
    fragments = [
        "the curve of a spine traced by a shaft of side light, the vertebrae creating a ripple of highlight and shadow, the rest of the body dissolving into blackness beyond the frame",
        "a single hand resting on a thigh, fingers slightly curled, nails catching a sliver of window light, the frame cropping at the wrist and mid-thigh",
        "the back of a neck where it meets the shoulders, a single tendon visible as the head turns away, the jawline just catching a rim light",
        "a thigh and hip in profile, stretch fabric crossing the frame diagonally, the shadow pooling beneath the form suggesting volume without showing the whole",
        "a foot with toes pressed into silk sheets, the arch creating a curve of tension, light catching the ankle bone and the hollow above it",
    ]
    lights = ["a single hard source from the side carving the form from darkness",
              "soft window light that grazes the surface revealing micro-texture",
              "rim light from behind that traces the edge of the form in a thin bright line",
              "a downward raking light that emphasizes every surface contour"]
    comps = ["at the extreme edge of the frame leaving negative space",
             "diagonally across the frame creating dynamic tension",
             "centered but tightly cropped so the form pushes against the boundaries"]
    results = []
    for _ in range(50):
        fr = random.choice(fragments)
        li = random.choice(lights)
        cp = random.choice(comps)
        pos = (
            f"realistic photographic extreme close-up of {fr}. "
            f"The frame reveals no face, no complete figure: only sculptural fragments that invite the "
            f"viewer to complete the form through imagination. "
            f"Lighting is {li}. "
            f"The tonal range is deliberately limited: the frame exists largely in the shadows, "
            f"with only select highlights revealing the form. Shadow detail is crucial: the dark areas "
            f"must hold the information of the body continuation even where it is not directly lit. "
            f"Skin texture is rendered with documentary clarity: pores, fine hairs, the subtle "
            f"variation in surface reflectivity across different parts of the body. "
            f"The composition is intentionally unbalanced, with the fragment placed {cp}. "
            f"The image is pure sculptural abstraction: a study of volume, surface, and the way "
            f"light defines form in space."
        )
        results.append([pos, neg("visible face or full figure",
                                 "center-framed conventional composition",
                                 "flat even lighting revealing too much",
                                 "airbrushed skin texture",
                                 "clinical or anatomical framing",
                                 "obvious or literal content")])
    return results

GENS["Bouidoir and Intimate Portraiture"] = {
    "Textiles and Touch (Fabric Study)": gen_textiles(),
    "Abstract Form (Fragmented Portrait)": gen_abstract(),
}

# ---- Pinup --------------------------------------------------------------

def gen_desert():
    scenes = [
        "a woman in a red bikini descending a sand dune, her shadow stretching long behind her on the golden slope",
        "a pinup pose leaning against a sun-bleached wooden signpost at a desert crossroads, heat haze shimmering on the horizon",
        "reclining on a woven blanket spread over warm sand, a wide-brimmed hat casting striped shadow across the face and chest",
        "standing in the doorway of an abandoned adobe shack, the frame creating a natural vignette of deep shadow against the blinding exterior",
        "a silhouette against the setting desert sun, the figure edges rimmed in gold, sand scattering in the wind at ankle height",
    ]
    lights = [
        "high noon sun from directly above, creating deep shadow pools under hat brims and in eye sockets",
        "late afternoon golden light raking across the dunes at a low angle, every grain of sand casting a tiny shadow",
        "the soft diffuse light of a dust-hazed sky, shadows barely present but color saturation intense",
        "the transition between sun and shadow at the edge of a mesa, half the scene in brilliant light and half in deep cool shadow",
    ]
    skies = ["a deep cobalt blue with no clouds, the blue saturating as it reaches the zenith",
             "streaked with high cirrus catching the warm colors of the sun",
             "pale and washed out at the horizon where dust scatters the light"]
    results = []
    for _ in range(50):
        sc = random.choice(scenes)
        li = random.choice(lights)
        sk = random.choice(skies)
        pos = (
            f"full-color pinup and bikini photography in a desert landscape: {sc}. "
            f"The desert light is intense and unforgiving: {li}. "
            f"The sky is {sk}. "
            f"Sand texture is critical: each grain visible in the lit zones, with the wind pattern "
            f"across the surface creating natural geometry. Skin tones are warm, catching the reflected "
            f"light from the sand, with sweat visible as micro-droplets on shoulders and arms. "
            f"The heat haze at the horizon creates a visible shimmer, distorting distant mesa edges. "
            f"Shadows are sharp-edged and dark but hold detail: the shadow side of the subject reveals "
            f"the color of the desert reflected as fill light."
        )
        results.append([pos, neg("soft studio lighting", "overcast or cloudy sky",
                                 "green screen or composite background",
                                 "flat shadowless lighting", "cool color temperature",
                                 "smooth airbrushed skin", "modern resort or pool setting")])
    return results

GENS["Pinup and Bikini"] = {"Desert Sun and Shadows (Dunes and Heat)": gen_desert()}

# ===========================================================================
# NATURE AND WILDLIFE
# ===========================================================================

def gen_forest_canopy():
    scenes = [
        "sunbeams piercing through a dense canopy of ancient oak and beech, creating distinct shafts of light in the morning mist",
        "a carpet of fallen leaves dappled with shifting patches of sunlight as the wind moves the branches overhead",
        "a narrow forest trail where light falls in irregular polygons between the overlapping layers of foliage",
        "a moss-covered fallen log with light filtering through the leaves above, creating a constellation of bright spots on the green surface",
        "the forest floor where patches of sunlight move across ferns and wildflowers, the light shifting every few seconds as clouds pass",
    ]
    results = []
    for _ in range(50):
        sc = random.choice(scenes)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {sc}. "
            f"The light quality is the primary subject: complex dappled patterns created by multiple "
            f"layers of canopy filtering the sun. Contrast is high within individual sunbeams but the "
            f"overall scene has a deep, rich tonality. The sunlit patches read as bright but not clipped, "
            f"with the green of sunlit leaves appearing yellow-green while shadowed foliage shifts toward "
            f"deep blue-green. Moss on the forest floor glows where the light hits it, and the dark "
            f"soil and bark absorb light, creating a natural high-contrast environment that tests "
            f"both highlight rolloff and shadow detail simultaneously."
        )
        results.append([pos, neg("flat even forest lighting", "artificial fill light in shadows",
                                 "oversaturated greens",
                                 "HDR-style equalized exposure")])
    return results

def gen_mountains():
    subjects = [
        "layered mountain ridges receding into blue-white haze at dawn",
        "a snow-covered peak catching the last light of sunset while the valley below has already fallen into deep blue shadow",
        "granite spires rising above a sea of clouds that fill the valley, the peaks like islands in a white ocean",
        "a mountain lake reflecting the surrounding peaks in perfect symmetry, the far shore softened by atmospheric haze",
        "alpine meadow in summer with wildflowers in the foreground, mountain peaks receding in layers of increasing blue",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}. "
            f"The composition emphasizes atmospheric perspective: each receding layer of the landscape "
            f"is paler and cooler than the one before it. The foreground is sharp with high contrast, "
            f"the mid-ground softer with reduced contrast, and the distant peaks are rendered as "
            f"blue-white silhouettes against the sky. Snow texture on the peaks shows the subtle "
            f"micro-shadowing of sun cups and wind-scoured ridges. Rock textures reveal the geology "
            f"in sharp detail where the light strikes at a grazing angle."
        )
        results.append([pos, neg("flat landscape with no atmospheric depth",
                                 "oversharpened distant mountains",
                                 "uniform green landscapes",
                                 "artificial saturation pushing the mountains blue")])
    return results

def gen_waters_edge():
    subjects = [
        "a still mountain lake at dawn, the surface like polished glass reflecting the surrounding peaks and sky",
        "a shallow stream flowing over smooth stones, the water surface broken by ripples that distort the reflection of overhanging branches",
        "a coastal rock pool at low tide, crystal clear water revealing colored pebbles, small anemones, and subtle sand texture",
        "reeds at the edge of a pond, their reflections stretching downward into the dark water",
        "a river bend where the water transitions from clear shallow rapids over rocks to a deep, dark pool",
    ]
    waters = [
        "perfect mirror reflections with no distortion, requiring precise vertical alignment in the frame",
        "rippled surface breaking reflections into fragmented colored shapes",
        "clear water allowing visibility of the submerged bed, with the light refracting through the water column",
        "the transition zone where shallow clear water meets deep dark water",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        w = random.choice(waters)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}. "
            f"The water surface renders with physical accuracy: {w}. "
            f"The color of the water ranges from crystal clear with green hints over sand "
            f"to deep teal fading to black in deeper areas. "
            f"Reflections are rendered with the correct brightness relative to the scene: "
            f"darker than the source by about one stop, with polarization effects visible at certain angles."
        )
        results.append([pos, neg("flat mirror reflections with no surface detail",
                                 "water that looks like glass or plastic",
                                 "unnaturally clear water without refraction",
                                 "reflections that are brighter than the source",
                                 "CGI-looking water surfaces")])
    return results

def gen_macro_flora():
    subjects = [
        "a single dewdrop balanced on the tip of a blade of grass",
        "the center of a sunflower in extreme close-up, the spiral pattern of seeds resolving in mathematical precision",
        "a rose petal surface in macro, the cellular structure creating a subtle pattern of light and color",
        "the veining pattern of a magnolia leaf backlit, every vein visible in amber and green",
        "a fern frond unfurling, the spiral tight at the tip and loosening toward the base",
    ]
    foci = [
        "every hair on the stem individually resolved",
        "the crystalline structure of the water droplet visible",
        "pollen grains distinct and three-dimensional",
        "each vein in the leaf mapping the path of nutrients",
        "the Fibonacci spiral of seeds clearly readable",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        fc = random.choice(foci)
        pos = (
            f"realistic photographic macro shot of {subj}. "
            f"The depth of field is shallow, isolating a narrow plane of focus while the foreground "
            f"and background dissolve into soft, organic bokeh. Focus is critically sharp: {fc}. "
            f"Color rendering captures the full saturation of the botanical subject without oversaturation. "
        )
        results.append([pos, neg("oversharpened beyond natural macro",
                                 "noise in shadow areas of macro detail",
                                 "flat depth of field, everything in focus",
                                 "fake or studio-quality water droplets",
                                 "plastic-looking petals with no translucency")])
    return results

def gen_big_cat():
    subjects = [
        "a leopard face in close-up, its eyes catching the last light of day",
        "a lioness resting in tall grass, her amber eyes half-closed",
        "a tiger emerging from shadow into a shaft of light",
        "a snow leopard face against granite, its pale blue eyes focused beyond the frame",
        "a cheetah profile against a golden savannah",
    ]
    furs = [
        "the thick winter coat showing layers of guard hair and undercoat",
        "the short sleek summer coat with each hair laying in a distinct direction",
        "the ruff of mane hair with individual strands crossing and separating",
        "the spotted coat with each rosette or spot having internal variation",
    ]
    bgs = ["golden-green out-of-focus bush", "blue haze of distant landscape",
           "dark green shadow of the forest", "warm brown of dry grass"]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        fu = random.choice(furs)
        bg = random.choice(bgs)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}. "
            f"The animal eyes are the focal point: the iris rendered with its full complexity of "
            f"color, the pupil crisp and round or narrowed to a slit depending on the light, "
            f"the catchlight shaped by the sky or environment. Fur texture is resolved at the individual "
            f"hair level in the lit zones: {fu}. "
            f"Whiskers are sharp, translucent at the tips, and catch the light with a subtle glow. "
            f"The background drops into a soft, natural {bg}. "
            f"The animal expression is alert but calm, with the innate dignity of an apex predator."
        )
        results.append([pos, neg("cartoon or anthropomorphic expression",
                                 "plastic-looking fur",
                                 "zoo or captive enclosure background",
                                 "overly sharpened eyes that look glassy",
                                 "distorted animal proportions",
                                 "domestic cat features on a big cat")])
    return results

def gen_bird_flight():
    subjects = [
        "a bald eagle banking in mid-flight, wings spread wide",
        "a flock of starlings swirling in a murmuration against the sunset sky",
        "a hummingbird suspended in mid-air, wings a blur of motion",
        "a heron taking off from still water, drops falling from primary feathers",
        "an owl in silent flight, wings fully extended, soft edge feathers creating silent airflow",
    ]
    motions = [
        "the wingtips may blur with motion while the body and head remain tack-sharp",
        "the entire bird is frozen in flight with every feather distinct against the sky",
        "the background blurs in a panning motion while the bird is sharp",
        "a fast shutter freezes water droplets mid-air around the bird",
    ]
    skies = ["deep blue with high contrast white clouds",
             "warm gold and orange of sunset",
             "flat overcast gray that makes the bird the only high-contrast element",
             "the pale blue of early morning with long low shadows"]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        mt = random.choice(motions)
        sk = random.choice(skies)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}. "
            f"The challenge is the simultaneous rendering of motion and stillness: {mt}. "
            f"Feather texture is rendered with individual barb and barbule structure visible in the lit areas. "
            f"The sky behind ranges from {sk}. "
        )
        results.append([pos, neg("frozen motion that looks like a taxidermy mount",
                                 "feathers that look like scales or plastic",
                                 "blur that looks like gaussian filter rather than motion",
                                 "perfectly frozen wingtips on a hummingbird",
                                 "fake sky backgrounds")])
    return results

def gen_ocean():
    subjects = [
        "a sea turtle gliding through sunlit water just below the surface",
        "a school of barracuda in the blue, their silver bodies catching the light from above",
        "coral reef in clear shallow water, every branch and polyp distinct",
        "a manta ray passing beneath, seen from above, wings spanning wide",
        "jellyfish suspended in dark water, their translucent bodies glowing against the deep blue-black",
    ]
    depths = [
        "the warmest color remaining is green, all red and orange absorbed by the first few meters",
        "only blue and violet remain, the entire scene rendered in shades of cobalt and indigo",
        "enough light penetrates to render full color, but the shadows have a distinct blue cast",
        "the water is so clear that color penetrates to surprising depth with minimal absorption",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        dp = random.choice(depths)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}. "
            f"Water acts as a natural filter, absorbing warm colors rapidly with depth. "
            f"At the subject depth, {dp}. "
            f"Caustic light patterns from the surface create moving, overlapping geometric shapes on "
            f"everything below: the subject, the bottom, particles in the water. "
            f"The surface above is visible as a silver-green mirror, rippling with wave motion."
        )
        results.append([pos, neg("water that looks like air with no color absorption",
                                 "perfectly clear water with no particles",
                                 "uniform lighting with no caustic patterns",
                                 "surface rendered as a sharp line",
                                 "unnaturally bright colors at depth")])
    return results

def gen_insect():
    subjects = [
        "a dragonfly perched on a reed, its compound eyes reflecting the world in thousands of tiny facets",
        "a jumping spider face in extreme macro, four forward-facing eyes each distinct",
        "a butterfly wing surface in extreme close-up, individual scales overlapping like roof tiles",
        "a praying mantis in profile, its serrated forelegs folded, the triangular head turned to face the camera",
        "a bee on a flower, pollen baskets on its legs packed with yellow granules",
    ]
    macros = [
        "the chitin exoskeleton has a microscopic texture like hammered metal",
        "the compound eye shows individual ommatidia, each a tiny hexagonal lens",
        "the hairs on the insect body emerge from individual sockets",
        "the wing membrane between veins has its own micro-texture",
    ]
    lights = ["soft diffused natural light",
              "a dedicated macro flash creating shadow that defines the three-dimensional structure",
              "backlight that makes translucent wings and bodies glow from within",
              "early morning dew catching the light across the entire subject"]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        mc = random.choice(macros)
        li = random.choice(lights)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic macro shot of {subj}. "
            f"The depth of field is measured in millimeters: only a sliver of the subject is in "
            f"critical focus, the rest falling into a smooth, natural bokeh. "
            f"At this magnification, surfaces that appear smooth to the naked eye reveal extraordinary complexity: {mc}. "
            f"Light is {li}. "
            f"The background is completely defocused, the colors of distant vegetation creating "
            f"a soft abstract backdrop. The subject fills the frame with its alien beauty."
        )
        results.append([pos, neg("depth of field too deep revealing distracting background",
                                 "flash that burns out highlight detail on reflective chitin",
                                 "insect that looks dead or pinned",
                                 "artificial studio background",
                                 "oversharpened creating artifacts on wing edges",
                                 "noise reduction eliminating hair and scale detail")])
    return results

def gen_desert_landscape():
    subjects = [
        "sand dunes at sunrise, the low light carving every ripple and curve into sharp relief",
        "a sandstone arch framing a distant mesa, the rock showing layers of sediment in horizontal bands",
        "the cracked floor of a dry lake bed, hexagonal patterns of dried mud stretching to the horizon",
        "a lone Joshua tree silhouetted against the setting sun, its twisted branches catching the orange light",
        "wind-blown sand at the base of a red rock formation, sand accumulating in curved drifts",
    ]
    palettes = ["ochre, sienna, and burnt umber in the rock layers",
                "the pale gold of quartz sand grading to deep amber in shadow",
                "the deep red of iron-rich sandstone against the pale blue of the sky",
                "the cream and buff of dry grass and the charcoal of ancient lava flows"]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pl = random.choice(palettes)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}. "
            f"The desert light is extreme, creating deep, sharp-edged shadows and "
            f"intense highlights. The color palette is warm and earthy: {pl}. "
            f"Sand texture is resolved at the grain level in the lit zones. "
            f"Heat haze shimmers at the horizon, distorting distant mesas. "
            f"The sky is a deep, dry blue with possibly a single high cirrus cloud."
        )
        results.append([pos, neg("flat desert lighting", "green or lush vegetation",
                                 "overcast desert sky", "wet-looking sand",
                                 "oversaturated red rocks looking artificial",
                                 "HDR equalization losing the high contrast",
                                 "blue-tinted shadows")])
    return results

def gen_autumn():
    subjects = [
        "a maple tree in full autumn color against a soft gray sky",
        "morning fog settling over a valley where the trees are transitioning",
        "a path through a woodland where the canopy has thinned, autumn leaves on the ground",
        "a single oak branch with leaves in various stages of transition",
        "a misty lake shoreline with autumn trees reflected in the still water",
    ]
    lights = [
        "soft and diffuse through a layer of thin cloud, creating even saturation across the leaves",
        "low-angle afternoon sun that backlights the leaves, making each translucent and glowing",
        "the flat, shadowless light of a foggy morning where colors appear more saturated",
        "the warm golden hour light that amplifies the warm tones and casts long amber shadows",
    ]
    airs = ["crisp and clear with the low sun creating sharp shadows",
            "heavy with moisture, softening edges and diffusing color",
            "filled with falling leaves, some caught mid-descent",
            "smoky from distant leaf fires, the haze warming the whole scene"]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        li = random.choice(lights)
        ar = random.choice(airs)
        st = random.choice(SHOT_TYPES)
        pos = (
            f"realistic photographic {st} of {subj}. "
            f"The color palette is the defining feature: golds from pale yellow-chartreuse to "
            f"deep amber, oranges from pumpkin to rust, reds from vermilion to deep burgundy, "
            f"all against the cooling blues and grays of the late autumn sky. "
            f"The lighting is {li}. "
            f"The ground layer of fallen leaves shows the full range of decay. "
            f"The air itself carries the quality of the season: {ar}."
        )
        results.append([pos, neg("oversaturated unnatural fall colors",
                                 "all leaves the same shade of red or gold",
                                 "summer green trees in an autumn scene",
                                 "flat lighting that does not show leaf translucency",
                                 "artificial-looking leaf colors",
                                 "winter bare trees with no remaining color")])
    return results

NATURE_SETS = {
    "Forest Canopy and Dappled Light": gen_forest_canopy(),
    "Mountain Majesty and Atmospheric Perspective": gen_mountains(),
    "Water's Edge and Reflections": gen_waters_edge(),
    "Macro Flora and Botanical Precision": gen_macro_flora(),
    "Big Cat Gaze and Predator Portrait": gen_big_cat(),
    "Bird in Flight and Feather Detail": gen_bird_flight(),
    "Ocean Depths and Underwater Light": gen_ocean(),
    "Insect Architecture and Micro Detail": gen_insect(),
    "Desert Solitude and Sand Stone": gen_desert_landscape(),
    "Seasonal Transitions in Autumn Palette": gen_autumn(),
}
GENS["Nature and Wildlife"] = NATURE_SETS

# ===========================================================================
# SPORTS AND ACTION
# ===========================================================================

def gen_frozen_motion():
    subjects = [
        "a diver suspended in mid-air above a pool, water droplets frozen around the body",
        "a soccer ball at the moment of impact with a player boot, the ball deforming slightly",
        "a sprinter captured at the instant both feet leave the blocks, muscles fully engaged",
        "a boxer landing a punch, sweat flying from the face, glove connecting with cheek",
        "a high jumper arching over the bar, the body in a perfect curve against the sky",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"Motion is frozen at the absolute peak of action. Every detail is crisp: "
            f"individual water droplets hang suspended, fabric ripples are caught mid-wave, "
            f"sweat flies in distinct beads. The shutter speed is high enough that even the "
            f"fastest elements are sharp, revealing the hidden geometry of motion that the "
            f"human eye cannot perceive in real time."
        )
        results.append([pos, neg("motion blur where there should be frozen action",
                                 "soft or smeared details in the subject",
                                 "unnaturally frozen water droplets",
                                 "stiff or posed-looking action")])
    return results

def gen_panning():
    subjects = [
        "a cyclist racing down a mountain road, the background a streak of green and gray",
        "a horse galloping along a track, the rail and crowd dissolving into speed lines",
        "a rally car cornering on gravel, the car sharp, the dust and background blurred",
        "a runner on a track, the lane lines and stands becoming horizontal streaks",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"Shot with a slow shutter speed while panning the camera to track the subject. "
            f"The subject is rendered with sharp detail: face, equipment, fabric texture all "
            f"clearly resolved. The background is a directional blur of speed lines, "
            f"creating a visceral sense of velocity. The transition from sharp subject to "
            f"blurred background is natural and photographic, not a digital mask."
        )
        results.append([pos, neg("motion blur applied to the subject",
                                 "digital speed lines added in post",
                                 "sharp background with blurred subject",
                                 "artificial panning effect",
                                 "ghosting or double-image effect on the subject")])
    return results

def gen_stadium():
    subjects = [
        "a football stadium from the highest tier, the field a green rectangle far below",
        "a basketball arena during a timeout, players gathered on court, crowd rising",
        "a baseball diamond at dusk, floodlights casting pools of light on the grass",
        "a tennis court from above, players tiny figures on the blue surface",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic establishing shot of {subj}. "
            f"The scale is epic: human figures are small elements within a vast architectural space. "
            f"Floodlights create dramatic pools of illumination with deep shadow areas between. "
            f"The crowd is rendered as thousands of distinct individuals, not a texture or pattern. "
            f"Architectural geometry of the stadium structure frames the composition with "
            f"clean lines and repeating structural elements. Dynamic range spans from "
            f"brightly lit field to shadowed upper decks."
        )
        results.append([pos, neg("crowd rendered as a uniform texture",
                                 "flat even stadium lighting",
                                 "overly clean or empty stands",
                                 "artificial depth of field on a wide shot")])
    return results

def gen_pre_competition():
    subjects = [
        "a boxer sitting in the corner of a locker room, hands wrapped, staring at the floor",
        "a swimmer standing at the edge of the pool, goggles pulled up, focused on the water",
        "a gymnast sitting on a bench, hands clasped, eyes closed in concentration",
        "a weightlifter standing before the barbell, hands chalked, visualizing the lift",
        "a runner adjusting starting blocks, jaw set, breathing steady",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"The moment before competition: tension, focus, and ritual preparation. "
            f"Lighting is atmospheric: {random.choice(['harsh locker room fluorescents creating deep shadows under eyes', 'the blue-white light of a pool hall reflecting off water', 'warm tungsten light in a gymnasium casting long shadows', 'the mixed light of arena corridors with exit signs and distant floodlights'])}. "
            f"Skin shows pores, stubble, sweat, the micro-texture of focus. "
            f"Fabric of uniform or training clothes has visible weave and fold. "
            f"The expression is introspective, not performative: this is the private moment "
            f"before the public performance."
        )
        results.append([pos, neg("smiling or performative expression",
                                 "studio-style beauty lighting",
                                 "perfect makeup or grooming",
                                 "clinical or sterile background",
                                 "distracting background elements")])
    return results

def gen_body_motion():
    subjects = [
        "a gymnast mid-routine on the balance beam, one leg extended behind, arms creating a line",
        "a swimmer at the start of a flip turn, body coiling, water foaming",
        "a long jumper in flight, limbs arranged for maximum distance, sand below",
        "a pole vaulter at the apex, body inverted, the pole bending",
        "a figure skater mid-spin, skirts flying, ice spray around the blade",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"Peak athletic form captured in full motion. Muscle definition is visible through "
            f"skin: the striation of engaged muscles, the tension of tendons, the vascularity "
            f"of exertion. Fabric moves with the body: folds and wrinkles shift dynamically. "
            f"Sweat appears as a sheen on skin with micro-droplets catching the light. "
            f"The sense of dynamic energy is palpable: this is not a posed held position "
            f"but a genuine moment of athletic performance frozen in time."
        )
        results.append([pos, neg("static or posed appearance",
                                 "muscles that look like anatomy textbook",
                                 "airbrushed or smooth skin",
                                 "fabric that does not move naturally with the body")])
    return results

def gen_water_sports():
    subjects = [
        "a surfer riding a wave, water spraying from the board edge, the barrel forming overhead",
        "a diver entering the water, a clean entry with minimal splash, bubbles streaming",
        "a water polo player reaching for the ball, water exploding around the arm",
        "a swimmer mid-stroke in a pool, the surface broken, bubbles trailing",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"Water and skin interaction is the central challenge. Water droplets are individual "
            f"and refractive, each one bending light. Spray patterns are organic and dynamic. "
            f"Caustic light patterns from the water surface play across skin and equipment. "
            f"The water itself ranges from crystal clear near the surface to a deep aquatic "
            f"blue at depth. Reflections on the water surface are distorted by the action."
        )
        results.append([pos, neg("water that looks like jelly or glass",
                                 "droplets that look painted on",
                                 "uniform clear water with no caustics",
                                 "static water surface during action")])
    return results

def gen_night_game():
    subjects = [
        "a baseball game under floodlights, the ball a white streak against the dark sky",
        "a football field at night, the green grass brilliantly lit against the black stands",
        "a boxing ring under the single overhead lamp, fighters casting sharp shadows on the canvas",
        "a night tennis match, the court a pool of light surrounded by darkness",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"Night sports lighting creates extreme color temperature mixing: warm tungsten "
            f"floodlights at 3200K against the cool blue of the night sky at 7000K+. "
            f"Light falls off dramatically from the brightly lit field to the dark stands. "
            f"Shadow detail in unlit areas holds just enough information to read the space. "
            f"Faces under floodlights show strong shadow from overhead direction."
        )
        results.append([pos, neg("flat even lighting on the field",
                                 "no color temperature variation",
                                 "brightly lit stands or background",
                                 "artificial fill light in shadow areas")])
    return results

def gen_combat():
    subjects = [
        "two boxers clinching, sweat flying, the impact of glove on skin visible",
        "a wrestler in a hold, muscles straining against muscle, fabric twisting",
        "a martial artist mid-kick, the kick connecting with a pad, impact spray",
        "two fighters trading blows, faces contorted with effort and impact",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"Raw physical intensity captured at close range. Sweat is visible as individual "
            f"droplets on skin. Impact distorts skin: the compression of a punch connecting, "
            f"the strain of a grapple. Ring lighting creates harsh shadows that cross faces "
            f"and bodies, emphasizing the geometry of combat. Skin texture is raw and real: "
            f"pores, stubble, the sheen of exertion, the red flush of effort."
        )
        results.append([pos, neg("blood or open wounds",
                                 "clean or staged-looking violence",
                                 "beauty lighting on fighters",
                                 "plastic or doll-like skin texture",
                                 "exaggerated or cartoon expressions")])
    return results

def gen_extreme_sports():
    subjects = [
        "a rock climber on a vertical face, chalk dust in the air, the valley far below",
        "a skier carving through powder, snow spraying, mountains receding in the background",
        "a snowboarder catching air above a halfpipe, the sky and snow a contrast of white and blue",
        "a BASE jumper in freefall, the cliff face receding above, the valley rushing below",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"Action in extreme natural environments creates a dual exposure challenge: "
            f"the athlete in shadow or partial light against a bright sky or vast landscape. "
            f"Snow texture is resolved at the grain level where lit. "
            f"Rock faces show geological detail, ice has crystalline structure. "
            f"The scale of the environment relative to the athlete is clear: human determination "
            f"against the vast indifference of nature."
        )
        results.append([pos, neg("flat exposure that does not handle the dynamic range",
                                 "artificial fill light on the athlete",
                                 "studio or gym setting",
                                 "fake or composite backgrounds")])
    return results

def gen_victory_defeat():
    subjects = [
        "a marathon runner crossing the finish line, arms raised, tears and sweat mixing",
        "a soccer team collapsing in a pile after a winning goal, joy and exhaustion",
        "a boxer kneeling on the canvas after a loss, head down, the other fighter raising gloves",
        "a gymnast embracing a coach after a routine, relief and joy on the face",
    ]
    results = []
    for _ in range(50):
        subj = random.choice(subjects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {subj}. "
            f"The raw emotion of competition aftermath. Tears are visible as individual droplets "
            f"on cheeks, not streaks. Skin shows the flush of exertion: reddened, sweating, real. "
            f"Embrace and contact are rendered with physical weight: arms compress fabric, "
            f"bodies lean into each other with the exhaustion of effort. "
            f"The light in these moments is often soft and diffuse: the flat light of "
            f"indoor arenas, the golden low sun of an outdoor event ending, "
            f"the mixed light of the tunnel after the stage."
        )
        results.append([pos, neg("actors pretending to be emotional",
                                 "perfect clean faces with no signs of exertion",
                                 "forced or staged composition",
                                 "clinical or empty background",
                                 "exaggerated theatrical emotion")])
    return results

SPORTS_SETS = {
    "Split-Second Frozen Motion": gen_frozen_motion(),
    "Speed Lines and Panning Blur": gen_panning(),
    "Stadium Drama and Epic Wide": gen_stadium(),
    "Pre-Competition Tension and Athlete Portrait": gen_pre_competition(),
    "Body in Motion and Athletic Form": gen_body_motion(),
    "Water Sports and Splash Spray": gen_water_sports(),
    "Night Game and Floodlit Action": gen_night_game(),
    "Combat Sport and Grit Sweat": gen_combat(),
    "Extreme Sport and Mountain Sky": gen_extreme_sports(),
    "Victory and Defeat in Emotional Release": gen_victory_defeat(),
}
GENS["Sports and Action"] = SPORTS_SETS

# ===========================================================================
# STILL LIFE AND PRODUCT
# ===========================================================================

def gen_glass():
    objects = ["a crystal whiskey tumbler catching window light", "a prism refracting sunlight into a spectrum",
               "a cut-glass vase with stems visible through the crystal", "a magnifying glass resting on aged paper",
               "a set of stacked glass beakers with colored liquids"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"The glass is rendered with physical accuracy: internal reflections, edge refraction, "
            f"and the subtle caustic patterns cast on the surface beneath. Highlights on the glass "
            f"surface are precisely shaped by the light source and follow the curvature of the object. "
            f"Transparency varies with thickness and angle, with edges appearing more opaque. "
            f"The background is visible through the glass, distorted by refraction. "
            f"no surface imperfections or specular hotspots are clipped."
        )
        results.append([pos, neg("glass that looks like plastic", "reflections that do not follow the surface curvature",
                                 "opaque or muddy glass edges", "no caustic light patterns",
                                 "oversharpened glass edges")])
    return results

def gen_metal():
    objects = ["a polished chrome faucet", "a brass sextant", "a stainless steel chef knife",
               "a silver teapot with ornate detailing", "a copper saucepan with riveted handle",
               "a vintage microphone with chrome grille"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"Polished metal demands precise specular highlight placement. The surface reflects "
            f"the environment in a distorted map, with the curvature of the object dictating "
            f"the shape and position of reflections. Gradient transitions on curved surfaces "
            f"are smooth, with no banding or stepping. Brushed metal shows directional micro-scratches "
            f"visible at grazing light angles. Polished metal shows mirror-like reflections "
            f"with slight color shift from the metal itself."
        )
        results.append([pos, neg("grainy or noisy metal gradients", "specular highlights that clip to white",
                                 "banding in smooth gradients", "reflections that do not match the surface curvature",
                                 "flat matte metal with no specularity")])
    return results

def gen_fabric():
    objects = ["velvet drapes with deep folds", "a silk scarf draped over a chair back",
               "a wool coat hanging in profile", "lace curtains backlit by window light",
               "a linen tablecloth with pressed creases", "a satin dress folded on a surface"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"The fabric is studied as a lesson in surface and form. Each fold is a geometric "
            f"consequence of gravity, tension, and the underlying form. Highlights track along "
            f"the crest of folds, shadows pool in the valleys between them. The weave of the "
            f"fabric is resolved at close range: warp and weft create the texture, with "
            f"individual threads visible where light strikes at a grazing angle. "
            f"The fabric weight is readable through the drape: heavy wool folds in wide, "
            f"soft curves; silk falls in tight, sharp creases; linen holds its shape with "
            f"crisp geometric folds."
        )
        results.append([pos, neg("fabric that looks painted rather than woven",
                                 "folds that defy gravity",
                                 "no visible weave texture",
                                 "uniform surface with no highlight variation",
                                 "digital fabric texture rather than photographic")])
    return results

def gen_food():
    objects = ["a perfectly plated main course with sauce drizzled in an arc",
               "a close-up of a croissant, flakes of pastry catching the light",
               "a bowl of fresh fruit with droplets of water on the skin",
               "a sliced cake with visible layers, frosting smooth",
               "a cup of coffee with latte art, foam bubbles distinct"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"Food photography demands precise texture rendering. Steam rises in visible wisps, "
            f"sauce has a glossy surface with specular highlights, meat shows the striation "
            f"of muscle fiber, vegetables have the subtle bloom of fresh produce. "
            f"Color rendering is critical: the red of a tomato, the green of herbs, "
            f"the brown of a seared crust must read as natural and appetizing. "
            f"Depth of field isolates the key element, the background dissolving into soft bokeh."
        )
        results.append([pos, neg("food that looks fake or plasticky",
                                 "oversaturated unnatural food colors",
                                 "steam that looks like smoke or fog",
                                 "flat lighting that removes texture",
                                 "perfect food with no natural imperfections")])
    return results

def gen_floral():
    objects = ["a bouquet of roses in a crystal vase", "a single peony in full bloom, petals overlapping",
               "a wildflower arrangement with diverse textures and colors",
               "tulips in a ceramic pitcher, each stem curving toward the light",
               "a branch of cherry blossoms against a dark background"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"Floral photography captures the full spectrum of botanical color and texture. "
            f"Petals are translucent where backlit, opaque where front-lit, with subtle color "
            f"gradients from the center to the edge. Stamens and pistils are resolved in detail: "
            f"individual pollen grains, the fine structure of the stamen filament. "
            f"Water droplets on petals act as tiny lenses, each one refracting the surrounding "
            f"colors. Leaves show vein patterns, the subtle variation of green, and the surface "
            f"texture of the leaf tissue."
        )
        results.append([pos, neg("flowers that look artificial or silk",
                                 "petals with no translucency",
                                 "oversaturated unnatural flower colors",
                                 "no visible stamen or pistil detail",
                                 "flat lighting that removes depth")])
    return results

def gen_vintage():
    objects = ["a rusted hand plane on a workbench", "a tarnished silver locket with a faded photograph inside",
               "a worn leather satchel with cracked stitching", "an aged brass oil lamp with patina",
               "chipped ceramic teacup with a visible crack", "weathered barn wood with old paint peeling"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"Age and use are written on every surface. Rust is not uniform: it forms in patches, "
            f"some areas flaking, others crusted, with the original metal visible beneath. "
            f"Patina on brass or copper varies from deep brown to green, layered and organic. "
            f"Leather shows creasing, scuffing, and the supple darkening of areas touched repeatedly. "
            f"Paint is chipped, cracked, and faded, revealing layers of previous colors beneath. "
            f"The light picks out the three-dimensional texture of decay: the raised edge of a "
            f"paint chip, the depth of a rust pit, the curl of peeling leather."
        )
        results.append([pos, neg("objects that look new or manufactured",
                                 "uniform or artificial patina",
                                 "rust that looks painted on",
                                 "clean edges and surfaces",
                                 "restored or polished appearance")])
    return results

def gen_liquid():
    objects = ["water being poured into a glass, the stream catching light",
               "olive oil and balsamic vinegar mixing on a plate", "milk splashing into a bowl in a crown formation",
               "a single drop of water hitting a still surface, ripples radiating outward",
               "whiskey being poured over a single large ice cube"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"Liquid in motion presents unique optical challenges. Each droplet is a lens: "
            f"spherical, refractive, with internal reflections that create bright spots and "
            f"dark edges. Splash formation follows fluid dynamics: the crown shape, the central "
            f"column, the satellite droplets. Surface tension is visible in the curve of a "
            f"meniscus, the skin of a droplet before it breaks. Different liquids have different "
            f"optical properties: water is transparent with white highlights, oil is amber and "
            f"thicker, milk is opaque with diffuse highlights."
        )
        results.append([pos, neg("droplets that look like solid spheres",
                                 "splashes that do not follow fluid dynamics",
                                 "water that looks too thick or too thin",
                                 "no internal refraction in droplets",
                                 "static or frozen liquid with no sense of motion")])
    return results

def gen_tools():
    objects = ["a workbench with scattered hand tools", "a potter wheel with a half-formed vase",
               "a carpenter bench with wood shavings and chisels",
               "a jeweler table with tiny tools and scattered gems",
               "a painter studio with brushes, tubes of paint, and a canvas in progress"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"A study in the material vocabulary of craft. Each surface in the frame has a distinct "
            f"texture: the wood grain of the workbench, the oiled metal of a tool, the fiber of "
            f"a brush, the dust and debris of work in progress. Light falls on the scene with "
            f"practical purpose: a desk lamp, window light, the warm glow of a workshop. "
            f"The composition tells a story of labor and creation: the tools arranged by use, "
            f"the half-completed work, the evidence of process visible everywhere."
        )
        results.append([pos, neg("clean sterile workshop with no signs of use",
                                 "tools arranged decoratively rather than functionally",
                                 "flat lighting that shows no texture",
                                 "new, unused tools",
                                 "no dust, shavings, or evidence of work")])
    return results

def gen_chiaroscuro():
    objects = ["a single apple on a wooden table", "a ceramic jug with a single lit edge",
               "a stack of old books, only the spine edges catching light",
               "a wilted flower in a glass, the stem visible in the lit zone",
               "a draped cloth with a single severe fold catching the light"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"A single light source creates the entire illumination of the scene. The light "
            f"falls off naturally from the bright highlight through midtones to deep, "
            f"transparent shadow. There is no fill light, no reflector: the shadow side carries "
            f"only ambient light and bounced color from nearby surfaces. The transition from "
            f"light to dark is smooth and continuous, the graduation of tone revealing the "
            f"three-dimensional form of the subject. The shadow areas are dark but not black: "
            f"the eye can read the continuation of the form into darkness."
        )
        results.append([pos, neg("fill light or reflector in the shadows",
                                 "pure black shadows with no information",
                                 "multiple light sources creating confusion",
                                 "flat even lighting",
                                 "HDR-style shadow lifting")])
    return results

def gen_minimalist():
    objects = ["a white porcelain bowl on a white surface", "a folded white linen napkin",
               "a white orchid against a white wall", "a white marble egg in a white ceramic dish",
               "a white paper crane on a white table"]
    results = []
    for _ in range(50):
        obj = random.choice(objects)
        pos = (
            f"realistic photographic {random.choice(SHOT_TYPES)} of {obj}. "
            f"The challenge is tonal separation in the near-white range. The white of the subject "
            f"must be distinguishable from the white of the background, with subtle differences in "
            f"warmth and brightness revealing the edge. Shadows on white are pale gray, not "
            f"warm or cool: neutral, delicate, just dark enough to define form. "
            f"Texture on white surfaces is revealed by the subtlest of highlights: a slight "
            f"sheen on porcelain, the weave of linen, the grain of marble. "
            f"The entire image exists in the upper two stops of the dynamic range, "
            f"requiring precise exposure and rendering to avoid blowing out the highlights "
            f"or muddying the whites into gray."
        )
        results.append([pos, neg("blown-out highlights with no detail",
                                 "white that reads as gray or beige",
                                 "visible shadows that should not be there",
                                 "color cast in the white balance",
                                 "crushed whites with no separation")])
    return results

STILL_SETS = {
    "Glass and Crystal Refraction": gen_glass(),
    "Metallic Lustre and Chrome Steel": gen_metal(),
    "Fabric Folds and Drapery Study": gen_fabric(),
    "Culinary Art and Food Plating": gen_food(),
    "Floral Arrangement and Botanical Precision": gen_floral(),
    "Vintage Objects and Patina Age": gen_vintage(),
    "Liquid in Motion and Pour Splash": gen_liquid(),
    "Tool and Craft Workshop Detail": gen_tools(),
    "Light and Shadow Single Source": gen_chiaroscuro(),
    "Minimalist White on White": gen_minimalist(),
}
GENS["Still Life and Product"] = STILL_SETS

# ===========================================================================
# Apply all generators to v5 data
# ===========================================================================

def apply_generators(data, generators):
    total = 0
    for deck in data["decks"]:
        dname = deck.get("display_name") or deck.get("model_name")
        dgen = generators.get(dname, {})
        for s in deck["sets"]:
            sname = s["name"]
            if sname in dgen:
                prompts = dgen[sname]
                s["prompts"] = prompts
                total += len(prompts)
                print(f"  {dname} :: {sname}: {len(prompts)} prompts")
    return total

filled = apply_generators(data, GENS)
V5.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
print(f"\nTotal prompts written: {filled}")

remaining = sum(1 for d in data["decks"] for s in d["sets"] if not s.get("prompts"))
total = sum(len(s.get("prompts",[])) for d in data["decks"] for s in d["sets"])
print(f"Total prompts in file: {total}")
print(f"Empty sets remaining: {remaining}")
