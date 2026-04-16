import { Approach } from "@/components/Approach";
import { Capabilities } from "@/components/Capabilities";
import { Footer } from "@/components/Footer";
import { Hero } from "@/components/Hero";
import { Nav } from "@/components/Nav";
import { Status } from "@/components/Status";

export default function Home() {
  return (
    <main className="min-h-screen">
      <Nav />
      <Hero />
      <Capabilities />
      <Approach />
      <Status />
      <Footer />
    </main>
  );
}
