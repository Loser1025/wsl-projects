'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';

type Faction = 'shu' | 'wei' | 'wu';

interface SparkData {
  x: number;
  y: number;
  z: number;
  seed: number;
  speedY: number;
  wobbleSpeed: number;
  wobbleScale: number;
}

const BANNER_WIDTH = 14;
const BANNER_HEIGHT = 22;
const BANNER_SEGMENTS_X = 20;
const BANNER_SEGMENTS_Y = 30;
const SPARKS_COUNT = 1200;
const WIND_FORCE = 0.6;

function createFactionTexture(faction: Faction): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 1024;
  const ctx = canvas.getContext('2d')!;

  const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
  if (faction === 'shu') {
    grad.addColorStop(0, '#0a2e1c');
    grad.addColorStop(0.5, '#05180e');
    grad.addColorStop(1, '#020a06');
  } else if (faction === 'wei') {
    grad.addColorStop(0, '#0a1d37');
    grad.addColorStop(0.5, '#040b17');
    grad.addColorStop(1, '#010307');
  } else {
    grad.addColorStop(0, '#3d0c0c');
    grad.addColorStop(0.5, '#1a0505');
    grad.addColorStop(1, '#050101');
  }
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (let i = 0; i < 50000; i++) {
    const x = Math.random() * canvas.width;
    const y = Math.random() * canvas.height;
    const opacity = Math.random() * 0.04;
    ctx.fillStyle = `rgba(255,255,255,${opacity})`;
    ctx.fillRect(x, y, 1, 1);
  }

  ctx.strokeStyle = faction === 'wei' ? 'rgba(100, 200, 255, 0.4)' : 'rgba(218, 165, 32, 0.4)';
  ctx.lineWidth = 16;
  ctx.strokeRect(20, 20, canvas.width - 40, canvas.height - 40);

  ctx.strokeStyle = faction === 'wei' ? 'rgba(100, 200, 255, 0.2)' : 'rgba(218, 165, 32, 0.2)';
  ctx.lineWidth = 4;
  ctx.strokeRect(36, 36, canvas.width - 72, canvas.height - 72);

  ctx.save();
  ctx.shadowColor = faction === 'wei' ? '#3b82f6' : '#ef4444';
  ctx.shadowBlur = 30;

  ctx.fillStyle = faction === 'wei' ? '#e0f2fe' : '#fef08a';
  ctx.font = 'bold 240px "Hiragino Mincho ProN", "Yu Mincho", serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  const char = faction === 'wei' ? '魏' : faction === 'wu' ? '呉' : '蜀';
  ctx.fillText(char, canvas.width / 2, canvas.height / 2 - 80);

  ctx.font = '60px "Hiragino Mincho ProN", "Yu Mincho", serif';
  ctx.fillStyle = 'rgba(255,255,255,0.7)';
  const leader = faction === 'wei' ? '曹' : faction === 'wu' ? '孫' : '劉';
  ctx.fillText(leader, canvas.width / 2, canvas.height / 2 - 260);

  ctx.restore();
  ctx.fillStyle = 'rgba(5, 2, 2, 0.95)';
  for (let i = 0; i < 5; i++) {
    ctx.beginPath();
    const py = 300 + Math.random() * 400;
    ctx.moveTo(canvas.width - 10, py);
    ctx.lineTo(canvas.width - 150 - Math.random() * 100, py + Math.random() * 40);
    ctx.lineTo(canvas.width - 10, py + 80);
    ctx.closePath();
    ctx.fill();
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export default function ThreeBackground() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    const fog = new THREE.FogExp2(0x0a0505, 0.015);
    scene.fog = fog;

    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 5, 32);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.6;
    container.appendChild(renderer.domElement);

    const ambientLight = new THREE.AmbientLight(0x110808, 0.5);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0xff4500, 3, 100);
    pointLight.position.set(0, -15, 5);
    scene.add(pointLight);

    const directionalLight = new THREE.DirectionalLight(0xffffff, 0);
    directionalLight.position.set(20, 40, -10);
    scene.add(directionalLight);

    // 雲海
    const cloudCanvas = document.createElement('canvas');
    cloudCanvas.width = 128;
    cloudCanvas.height = 128;
    const cloudCtx = cloudCanvas.getContext('2d')!;
    const cloudGrad = cloudCtx.createRadialGradient(64, 64, 0, 64, 64, 64);
    cloudGrad.addColorStop(0, 'rgba(120, 50, 40, 0.13)');
    cloudGrad.addColorStop(0.3, 'rgba(50, 20, 20, 0.06)');
    cloudGrad.addColorStop(0.7, 'rgba(15, 5, 5, 0.015)');
    cloudGrad.addColorStop(1, 'rgba(0,0,0,0)');
    cloudCtx.fillStyle = cloudGrad;
    cloudCtx.fillRect(0, 0, 128, 128);
    const cloudTex = new THREE.CanvasTexture(cloudCanvas);
    cloudTex.colorSpace = THREE.SRGBColorSpace;

    const cloudGeo = new THREE.PlaneGeometry(120, 120);
    const cloudMat = new THREE.MeshBasicMaterial({
      map: cloudTex,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    const cloudParticles: THREE.Mesh[] = [];
    for (let i = 0; i < 25; i++) {
      const mesh = new THREE.Mesh(cloudGeo, cloudMat);
      mesh.position.set(Math.random() * 200 - 100, Math.random() * 40 - 30, Math.random() * 50 - 60);
      mesh.rotation.z = Math.random() * 360;
      mesh.scale.set(1.5, 1.5, 1.5);
      scene.add(mesh);
      cloudParticles.push(mesh);
    }

    // 火の粉
    const sparkCanvas = document.createElement('canvas');
    sparkCanvas.width = 32;
    sparkCanvas.height = 32;
    const sparkCtx = sparkCanvas.getContext('2d')!;
    const sparkGrad = sparkCtx.createRadialGradient(16, 16, 0, 16, 16, 16);
    sparkGrad.addColorStop(0, 'rgba(255, 255, 255, 1)');
    sparkGrad.addColorStop(0.2, 'rgba(255, 150, 0, 1)');
    sparkGrad.addColorStop(0.5, 'rgba(200, 50, 0, 0.6)');
    sparkGrad.addColorStop(1, 'rgba(0,0,0,0)');
    sparkCtx.fillStyle = sparkGrad;
    sparkCtx.fillRect(0, 0, 32, 32);
    const sparkTex = new THREE.CanvasTexture(sparkCanvas);
    sparkTex.colorSpace = THREE.SRGBColorSpace;

    const sparksGeometry = new THREE.BufferGeometry();
    const positions = new Float32Array(SPARKS_COUNT * 3);
    const colors = new Float32Array(SPARKS_COUNT * 3);
    const sparkCoords: SparkData[] = [];

    for (let i = 0; i < SPARKS_COUNT; i++) {
      const x = Math.random() * 80 - 40;
      const y = Math.random() * 50 - 25;
      const z = Math.random() * 40 - 20;

      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      sparkCoords.push({
        x,
        y,
        z,
        seed: Math.random() * 100,
        speedY: 2.0 + Math.random() * 3.0,
        wobbleSpeed: 1.0 + Math.random() * 2.0,
        wobbleScale: 0.2 + Math.random() * 0.5,
      });

      colors[i * 3] = 0.8 + Math.random() * 0.2;
      colors[i * 3 + 1] = 0.2 + Math.random() * 0.4;
      colors[i * 3 + 2] = 0.0;
    }

    sparksGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    sparksGeometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const sparksMaterial = new THREE.PointsMaterial({
      size: 0.6,
      vertexColors: true,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      map: sparkTex,
    });

    const sparksParticleSystem = new THREE.Points(sparksGeometry, sparksMaterial);
    scene.add(sparksParticleSystem);

    // 軍旗（クロスシミュレーション）
    let bannerMesh: THREE.Mesh | null = null;
    let poleMesh: THREE.Mesh | null = null;

    function createFlagPole() {
      if (poleMesh) scene.remove(poleMesh);
      const poleGeo = new THREE.CylinderGeometry(0.15, 0.2, 32, 8);
      const poleMat = new THREE.MeshStandardMaterial({ color: 0x1a1515, roughness: 0.5, metalness: 0.8 });
      poleMesh = new THREE.Mesh(poleGeo, poleMat);
      poleMesh.position.set(-16, -1, -4);
      poleMesh.rotation.y = Math.PI / 6;
      scene.add(poleMesh);
    }

    function createBanner(faction: Faction) {
      const geometry = new THREE.PlaneGeometry(BANNER_WIDTH, BANNER_HEIGHT, BANNER_SEGMENTS_X, BANNER_SEGMENTS_Y);
      const texture = createFactionTexture(faction);
      const material = new THREE.MeshStandardMaterial({
        map: texture,
        emissiveMap: texture,
        emissive: 0xffffff,
        emissiveIntensity: 0.7,
        side: THREE.DoubleSide,
        roughness: 0.8,
        metalness: 0.1,
        flatShading: false,
        alphaTest: 0.1,
      });

      bannerMesh = new THREE.Mesh(geometry, material);
      bannerMesh.position.set(-9, -1, -2);
      bannerMesh.rotation.y = Math.PI / 6;
      scene.add(bannerMesh);

      createFlagPole();
    }

    createBanner('wu');

    // マウス追従（パララックス）
    const mouse = { x: 0, y: 0, targetX: 0, targetY: 0 };
    let lightningIntensity = 0;
    let nextLightningTime = 3.0;

    function onMouseMove(event: MouseEvent) {
      mouse.targetX = (event.clientX / window.innerWidth) * 2 - 1;
      mouse.targetY = -(event.clientY / window.innerHeight) * 2 + 1;
    }

    function onTouchMove(event: TouchEvent) {
      if (event.touches.length > 0) {
        mouse.targetX = (event.touches[0].clientX / window.innerWidth) * 2 - 1;
        mouse.targetY = -(event.touches[0].clientY / window.innerHeight) * 2 + 1;
      }
    }

    function onWindowResize() {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    }

    window.addEventListener('resize', onWindowResize);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('touchmove', onTouchMove, { passive: true });

    function simulateCloth(time: number) {
      if (!bannerMesh) return;
      const positionAttribute = bannerMesh.geometry.attributes.position;

      for (let y = 0; y <= BANNER_SEGMENTS_Y; y++) {
        for (let x = 0; x <= BANNER_SEGMENTS_X; x++) {
          const index = x + y * (BANNER_SEGMENTS_X + 1);
          const initX = (x / BANNER_SEGMENTS_X - 0.5) * BANNER_WIDTH;
          const initY = (0.5 - y / BANNER_SEGMENTS_Y) * BANNER_HEIGHT;

          const speedFactor = time * 3.5;
          const windWeight = x / BANNER_SEGMENTS_X;

          const waveZ =
            Math.sin(x * 0.3 - speedFactor + y * 0.1) * 1.8 * windWeight * WIND_FORCE +
            Math.cos(y * 0.4 - speedFactor * 0.5) * 0.8 * windWeight +
            Math.sin((x + y) * 0.1 - speedFactor * 1.2) * 0.4 * windWeight * WIND_FORCE;

          const waveX = Math.sin(y * 0.2 + speedFactor) * 0.3 * windWeight * WIND_FORCE;

          positionAttribute.setXYZ(index, initX + waveX, initY, waveZ);
        }
      }

      positionAttribute.needsUpdate = true;
      bannerMesh.geometry.computeVertexNormals();
    }

    function updateSparks(delta: number, time: number) {
      const positionArray = sparksGeometry.attributes.position.array as Float32Array;

      for (let i = 0; i < SPARKS_COUNT; i++) {
        const data = sparkCoords[i];
        data.y += data.speedY * delta;

        const baseWind = 4.0 * WIND_FORCE;
        const mouseWind = mouse.x * 6.0;
        data.x += (baseWind + mouseWind) * delta;

        data.x += Math.sin(time * data.wobbleSpeed + data.seed) * data.wobbleScale * 0.1;
        data.z += Math.cos(time * data.wobbleSpeed * 0.8 + data.seed) * data.wobbleScale * 0.1;

        if (data.y > 25 || data.x > 50) {
          data.y = -25 - Math.random() * 5;
          data.x = -40 + Math.random() * 20;
          data.z = Math.random() * 40 - 20;
        }

        positionArray[i * 3] = data.x;
        positionArray[i * 3 + 1] = data.y;
        positionArray[i * 3 + 2] = data.z;
      }

      sparksGeometry.attributes.position.needsUpdate = true;
    }

    function updateEnvironment(time: number, delta: number) {
      pointLight.intensity = 2.0 + Math.sin(time * 8) * 0.8 + Math.cos(time * 3) * 0.4;
      pointLight.position.x = Math.sin(time) * 10 - 5;

      cloudParticles.forEach((cloud) => {
        cloud.rotation.z += 0.02 * delta;
        cloud.position.x += (1.0 * WIND_FORCE + mouse.x * 2.0) * delta;
        if (cloud.position.x > 100) cloud.position.x = -100;
      });

      nextLightningTime -= delta;
      if (nextLightningTime <= 0) {
        lightningIntensity = 3.0 + Math.random() * 4.0;
        nextLightningTime = 4.0 + Math.random() * 8.0;
      }

      if (lightningIntensity > 0) {
        lightningIntensity *= Math.exp(-6.0 * delta);
        directionalLight.intensity = lightningIntensity;
        fog.color.setHex(lightningIntensity > 0.5 ? 0x1f242d : 0x0a0505);
        ambientLight.color.setRGB(
          0.05 + lightningIntensity * 0.1,
          0.04 + lightningIntensity * 0.15,
          0.04 + lightningIntensity * 0.2
        );
      } else {
        directionalLight.intensity = 0;
        fog.color.setHex(0x0a0505);
        ambientLight.color.setRGB(0.06, 0.03, 0.03);
      }
    }

    const clock = new THREE.Clock();
    let animationFrameId = 0;

    function animate() {
      animationFrameId = requestAnimationFrame(animate);

      const delta = clock.getDelta();
      const time = clock.getElapsedTime();

      mouse.x += (mouse.targetX - mouse.x) * 0.05;
      mouse.y += (mouse.targetY - mouse.y) * 0.05;

      camera.position.x = mouse.x * 4;
      camera.position.y = 5 + mouse.y * 2;
      camera.lookAt(new THREE.Vector3(-2, 3, 0));

      simulateCloth(time);
      updateSparks(delta, time);
      updateEnvironment(time, delta);

      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', onWindowResize);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('touchmove', onTouchMove);

      cloudGeo.dispose();
      cloudMat.dispose();
      cloudTex.dispose();
      sparksGeometry.dispose();
      sparksMaterial.dispose();
      sparkTex.dispose();
      if (bannerMesh) {
        bannerMesh.geometry.dispose();
        (bannerMesh.material as THREE.Material).dispose();
      }
      if (poleMesh) {
        poleMesh.geometry.dispose();
        (poleMesh.material as THREE.Material).dispose();
      }
      renderer.dispose();
      container.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={containerRef} className="fixed inset-0 z-0 pointer-events-none" />;
}
