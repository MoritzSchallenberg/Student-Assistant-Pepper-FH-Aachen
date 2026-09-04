# RealSense-Kalibrieranleitung (Kameramontage)

Stand: 2026-09-04. Teil von Entwicklungsauftrag 1, Abschnitt 3. **Alle
Werte in `ros2/autonomy_ws/src/ihk_pepper_navigation/config/realsense_extrinsics.yaml`
sind aktuell Platzhalter** (Translation `0,0,0`, Rotation Identität,
`is_calibrated: false`) -- diese Anleitung beschreibt, wie die echten
Werte ermittelt werden, sobald eine RealSense real auf Peppers Kopf
montiert ist. In dieser Session war keine RealSense-Hardware
angeschlossen, die Werte wurden **nicht** vermessen.

## Warum das überhaupt nötig ist

Die RealSense ist auf Peppers Kopf montiert, nicht an einem festen
Punkt der Basis. Der TF-Baum sieht deshalb so aus:

```
base_link → realsense_mount_link → camera_link (RealSense-Treiber übernimmt ab hier)
                                       └→ camera_color_optical_frame
                                       └→ camera_depth_optical_frame
```

`base_link → realsense_mount_link` ist die **Montagepose** (fester
Versatz, wird hier vermessen). `realsense_mount_link → camera_link` ist
bewusst Identität (der Montagepunkt *ist* die Kameraposition in diesem
Modell). Alles ab `camera_link` (die optischen Frames, die genaue
Objektiv-Geometrie) publiziert der `realsense2_camera`-Treiber bereits
selbst korrekt -- das wird hier **nicht** nachgebaut.

## Was gemessen werden muss

1. **Translation** (`translation_m: {x, y, z}`): Abstand vom Ursprung von
   `base_link` (üblicherweise Boden-/Basis-Mittelpunkt, siehe
   `ros2/robot_model/src/pepper_description/urdf/pepper.urdf` für die
   exakte Konvention) bis zum optischen Zentrum der RealSense, in Metern,
   im `base_link`-Koordinatensystem (x = vorwärts, y = links, z = oben).

2. **Rotation** (`rotation_rpy_rad: {roll, pitch, yaw}`): Orientierung
   der Kamera relativ zu `base_link`, in Radiant. Bei einer nach vorne
   ausgerichteten, nicht gekippten Kamera sind alle drei Werte 0 --
   sitzt die Kamera schräg oder leicht nach unten geneigt am Kopf, muss
   das hier eingetragen werden.

## Werkzeuge/Vorgehen (Vorschlag, nicht vorgeschrieben)

- **Physisch nachmessen**: Maßband/Schieblehre ab einem bekannten
  Referenzpunkt an Peppers Basis bis zum RealSense-Gehäuse. Grob, aber
  schnell und ohne Zusatzwerkzeug.
- **Genauer per Checkerboard/ArUco-Kalibrierung**: ein bekanntes Muster
  vor Pepper platzieren, `camera_calibration`- oder
  `apriltag_ros`-artige Tools nutzen, um die Kamerapose relativ zu einem
  bekannten Weltpunkt zu bestimmen, davon relativ zu `base_link`
  zurückrechnen (braucht zusätzlich Peppers Kopfgelenkwinkel zum
  Messzeitpunkt, siehe unten).
- **Per URDF/CAD**, falls ein vollständiges Pepper-CAD-Modell mit
  RealSense-Halterung vorliegt: Werte direkt daraus übernehmen.

**Wichtig**: da die RealSense am *Kopf* sitzt, gilt die vermessene
Transformation nur für EINE bestimmte Kopfpose (`HeadYaw=0`,
`HeadPitch=0` empfohlen, passend zu `navigation_head_pose` in
`camera_pose_gate_node.py`). Die Vermessung sollte deshalb exakt in der
späteren Navigations-Kopfpose stattfinden.

## Werte eintragen

```yaml
# ros2/autonomy_ws/src/ihk_pepper_navigation/config/realsense_extrinsics.yaml
realsense_extrinsics:
  parent_frame: "base_link"
  mount_frame: "realsense_mount_link"
  camera_root_frame: "camera_link"
  translation_m: {x: <gemessen>, y: <gemessen>, z: <gemessen>}
  rotation_rpy_rad: {roll: <gemessen>, pitch: <gemessen>, yaw: <gemessen>}
  is_calibrated: true   # erst auf true setzen, wenn echte Werte eingetragen sind
```

`is_calibrated: false` ist der sichere Ausgangszustand -- solange dieser
Wert `false` ist, warnt `realsense_static_tf.launch.py` beim Start
deutlich, dass die TF-Kette nicht vertrauenswürdig ist.

## Nach der Kalibrierung prüfen

```bash
cd ros2/autonomy_ws
source install/setup.bash
ros2 launch ihk_pepper_navigation realsense_static_tf.launch.py
# in einem zweiten Terminal:
ros2 run tf2_ros tf2_echo base_link camera_link
```

Die ausgegebene Translation/Rotation muss den eingetragenen Werten
entsprechen. Ein voller End-to-End-Plausibilitätstest (bekanntes Objekt
in bekanntem Abstand vor Pepper platzieren, per
`ihk_pepper_perception/deprojection.py`-Pipeline die berechnete 3D-Position
mit der real gemessenen vergleichen) ist **nicht** Teil dieses Auftrags
-- das braucht eine echte, angeschlossene RealSense (siehe
docs/DEVELOPMENT_ORDER_01_REPORT.md, "Nicht getestete Hardware").
